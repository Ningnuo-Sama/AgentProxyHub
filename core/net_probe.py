#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""纯 Python 的 SOCKS5h + HTTPS 探测内核（彻底取代 curl.exe 子进程）。

为什么存在这个模块（黑窗根因治理）：
    Windows 下只要通过 subprocess 拉起控制台程序（curl.exe / cmd.exe / pwsh.exe），
    即使父进程是 pythonw.exe，系统仍会为子进程分配 conhost.exe 控制台宿主；
    在 CREATE_NO_WINDOW / -WindowStyle Hidden 组合下，仍然会在桌面上出现
    "黑窗一闪"（一指弹）。定时任务与常驻守护进程每 5 分钟扫描上百个端口时，
    就会变成连环黑窗风暴。

    因此探测层改为：在 Python 进程内直接用 socket 建立 SOCKS5 隧道 + ssl 包一层 TLS，
    自行发送 HTTP/HTTPS 请求。全程零子进程 → 零 conhost → 零黑窗。

对外只暴露两个函数：
    https_get_via_socks5(port, host, path, timeout) -> (status_code, body_bytes)
    probe_google_country_direct(port, timeout)      -> str
"""
from __future__ import annotations

import re
import socket
import ssl
import time
from typing import Tuple

__all__ = ["https_get_via_socks5", "probe_google_country_direct"]

_GOOGLE_TERMS_HOST = "policies.google.com"
_GOOGLE_TERMS_PATH = "/terms"

# Google 页面里的自判国家标记
_RE_COUNTRY = re.compile(r"Country version:</a>\s*([^<]+)", re.IGNORECASE)
_RE_COUNTRY2 = re.compile(r"country-version.*?([A-Za-z ]+)</p>", re.IGNORECASE)


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    """严格读取 n 字节，不足则抛错（SOCKS5 握手需要精确分帧）。"""
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise OSError("socks5: connection closed early")
        buf.extend(chunk)
    return bytes(buf)


def _socks5_connect(proxy_host: str, proxy_port: int, dest_host: str,
                    dest_port: int, timeout: float) -> socket.socket:
    """建立到 dest_host:dest_port 的 SOCKS5 隧道（域名在代理解析，即 socks5h 语义）。"""
    sock = socket.create_connection((proxy_host, proxy_port), timeout=timeout)
    try:
        sock.settimeout(timeout)
        # 握手：只声明"无认证"
        sock.sendall(b"\x05\x01\x00")
        greeting = _recv_exact(sock, 2)
        if greeting[0] != 0x05:
            raise OSError("socks5: bad version in greeting")
        if greeting[1] != 0x00:
            raise OSError(f"socks5: auth method rejected ({greeting[1]})")

        # CONNECT：ATYP=0x03 域名（socks5h，DNS 交给代理）
        host_bytes = dest_host.encode("idna") if _needs_idna(dest_host) else dest_host.encode("ascii", "ignore")
        req = (b"\x05\x01\x00\x03" + bytes([len(host_bytes)]) + host_bytes
               + int(dest_port).to_bytes(2, "big"))
        sock.sendall(req)

        head = _recv_exact(sock, 4)
        if head[1] != 0x00:
            raise OSError(f"socks5: connect failed code={head[1]}")
        atyp = head[3]
        if atyp == 0x01:      # IPv4
            _recv_exact(sock, 4)
        elif atyp == 0x03:    # 域名
            ln = _recv_exact(sock, 1)[0]
            _recv_exact(sock, ln)
        elif atyp == 0x04:    # IPv6
            _recv_exact(sock, 16)
        _recv_exact(sock, 2)  # 绑定端口
        return sock
    except Exception:
        try:
            sock.close()
        except Exception:
            pass
        raise


def _needs_idna(host: str) -> bool:
    try:
        host.encode("ascii")
        return False
    except UnicodeEncodeError:
        return True


def _dechunk(body: bytes) -> bytes:
    """解码 Transfer-Encoding: chunked 的响应体。"""
    out = bytearray()
    pos = 0
    while True:
        eol = body.find(b"\r\n", pos)
        if eol < 0:
            break
        size_field = body[pos:eol].split(b";")[0].strip()
        try:
            size = int(size_field, 16)
        except ValueError:
            break
        pos = eol + 2
        if size == 0:
            break
        out.extend(body[pos:pos + size])
        pos += size + 2
    return bytes(out)


def https_get_via_socks5(port: int, host: str, path: str = "/",
                         timeout: float = 10.0) -> Tuple[int, bytes]:
    """经本地 SOCKS5 端口(port) 访问 https://host/path，返回 (http状态码, 正文)。

    失败时返回 (0, b"")，绝不抛异常、绝不产生子进程。
    """
    raw = None
    tls = None
    try:
        raw = _socks5_connect("127.0.0.1", int(port), host, 443, timeout)
        ctx = ssl.create_default_context()
        tls = ctx.wrap_socket(raw, server_hostname=host)
        # 不吃 gzip：只要原始文本，避免解压依赖
        req = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0 Safari/537.36\r\n"
            "Accept: text/html,application/json,*/*\r\n"
            "Accept-Encoding: identity\r\n"
            "Connection: close\r\n\r\n"
        )
        tls.sendall(req.encode("ascii"))

        chunks = []
        while True:
            block = tls.recv(65536)
            if not block:
                break
            chunks.append(block)
        data = b"".join(chunks)

        head, sep, body = data.partition(b"\r\n\r\n")
        if not sep:
            return 0, b""
        status = 0
        m = re.match(rb"HTTP/\d\.\d\s+(\d{3})", head)
        if m:
            status = int(m.group(1))
        if b"transfer-encoding: chunked" in head.lower():
            body = _dechunk(body)
        return status, body
    except Exception:
        return 0, b""
    finally:
        for s in (tls, raw):
            try:
                if s is not None:
                    s.close()
            except Exception:
                pass


def probe_google_country_direct(port: int, timeout: float = 8.0) -> str:
    """经本地 SOCKS5 端口读取 Google 自判国家（纯 Python，无 curl、无黑窗）。

    返回国家名（如 "United States"）；无法判定时返回 "Unknown" 或 "FAIL"。
    """
    status, body = https_get_via_socks5(port, _GOOGLE_TERMS_HOST, _GOOGLE_TERMS_PATH, timeout)
    if status == 0 or not body:
        return "FAIL"
    text = body.decode("utf-8", errors="replace")
    m = _RE_COUNTRY.search(text)
    if m:
        return m.group(1).strip()
    m2 = _RE_COUNTRY2.search(text)
    if m2:
        return m2.group(1).strip()
    if "policies.google.com" in text:
        return "Unknown"
    return "FAIL"


def probe_ip_direct(port: int, timeout: float = 10.0) -> Tuple[int, str, str, int]:
    """经本地 SOCKS5 端口取物理出口信息。

    返回 (http状态码, ip, country_code, 耗时毫秒)；失败返回 (0, "", "", -1)。
    """
    t0 = time.monotonic()
    status, body = https_get_via_socks5(port, "ipwho.is", "/", timeout)
    latency = int((time.monotonic() - t0) * 1000)
    if status != 200 or not body:
        return 0, "", "", -1
    import json as _json
    try:
        info = _json.loads(body.decode("utf-8", errors="replace"))
    except Exception:
        return 0, "", "", -1
    return status, (info.get("ip") or ""), (info.get("country_code") or "").upper(), latency
