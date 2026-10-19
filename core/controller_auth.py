"""业务内核控制器认证与固定端口校验（从 personal_route.py 迁出，2026-10-19）。

迁出原因：个人出海模块下线后，`core/tun_controller.py`（业务侧）仍需要两个
纯工具函数——读取控制器认证信息、校验 125 个固定监听端口。它们与TUN/出海
完全无关，只是历史上被放在 personal_route.py 里。

**这两个函数不涉及 TUN、不启动进程、不修改配置，只读 YAML 并做校验。**
"""
from __future__ import annotations

import ipaddress
from pathlib import Path
from typing import Any, Mapping

# 业务端口池：21001-21080（蜂窝 fw-*）+ 22001-22045（星辰 xc-*）= 125 个
FIXED_PORTS = frozenset(range(21001, 21081)) | frozenset(range(22001, 22046))


def fixed_listener_map(config: Mapping[str, Any]) -> dict[int, str]:
    """Require exactly the original 125 fixed SOCKS ports and direct node targets."""
    result = {}
    for item in config.get("listeners", []):
        port = item.get("port")
        if port not in FIXED_PORTS:
            continue
        expected = ("fw-" if port < 22000 else "xc-") + str(port)
        if port in result or item.get("proxy") != expected:
            raise ValueError("fixed_listener_mapping_invalid")
        result[port] = expected
    if result.keys() != FIXED_PORTS:
        raise ValueError("fixed_listener_ports_missing")
    return result


def runtime_controller_auth(config_path: str | Path) -> tuple[str, dict[str, str]]:
    """Read controller auth from the selected runtime YAML; never return in UI output.

    PyYAML is needed only for this function. Only loopback controller addresses
    are accepted. Returned headers are sensitive and must not be logged.
    """
    import yaml

    with Path(config_path).open(encoding="utf-8-sig") as handle:
        config = yaml.safe_load(handle)
    endpoint = str(config.get("external-controller") or "")
    host, separator, port = endpoint.rpartition(":")
    host = host.strip("[]")
    try:
        if not separator or not ipaddress.ip_address(host).is_loopback or not 1 <= int(port) <= 65535:
            raise ValueError
    except ValueError:
        raise ValueError("loopback_controller_required") from None
    secret = config.get("secret")
    if not isinstance(secret, str) or not secret:
        raise ValueError("controller_auth_missing")
    return "http://" + endpoint, {"Authorization": "Bearer " + secret}