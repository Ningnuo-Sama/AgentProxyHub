#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Provider 刷新薄适配：真实 YAML 校验、跨进程串行与可证据化回退。"""
import contextlib, hashlib, os, tempfile, threading
try:
    import yaml
except ImportError:
    yaml = None
try:
    import msvcrt
except ImportError:
    msvcrt = None
    import fcntl

_LOCKS, _LOCKS_GUARD = {}, threading.Lock()
def _path_lock(path):
    key = os.path.normcase(os.path.abspath(path))
    with _LOCKS_GUARD: return _LOCKS.setdefault(key, threading.Lock())
@contextlib.contextmanager
def _file_lock(path):
    lock_path = os.path.normcase(os.path.abspath(path)) + ".lock"
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    with open(lock_path, "a+b") as fh:
        if msvcrt:
            fh.seek(0); msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
        else: fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try: yield
        finally:
            if msvcrt:
                fh.seek(0); msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            else: fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
def _atomic_bytes(path, content):
    directory=os.path.dirname(os.path.abspath(path)) or "."; fd,tmp=tempfile.mkstemp(prefix=".provider-",suffix=".tmp",dir=directory)
    try:
        with os.fdopen(fd,"wb") as fh: fh.write(content); fh.flush(); os.fsync(fh.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)
def _validate_nodes(nodes):
    if not nodes: raise ValueError("provider proxies 不能为空")
    allowed={"socks5","socks5h","http","https","ss","vmess","vless","trojan","hysteria2","tuic","anytls"}
    for i,node in enumerate(nodes):
        if not isinstance(node,dict): raise ValueError(f"provider 节点 {i} 必须是对象")
        if not isinstance(node.get("name"),str) or not node["name"].strip(): raise ValueError(f"provider 节点 {i} 缺少 name")
        if not isinstance(node.get("server"),str) or not node["server"].strip(): raise ValueError(f"provider 节点 {i} 缺少 server")
        port=node.get("port")
        if isinstance(port,bool) or isinstance(port,float) or not isinstance(port,(int,str)):
            raise ValueError(f"provider 节点 {i} port 无效")
        try: port=int(port)
        except (TypeError,ValueError): raise ValueError(f"provider 节点 {i} port 无效")
        if not 1<=port<=65535: raise ValueError(f"provider 节点 {i} port 越界")
        typ=node.get("type")
        if not isinstance(typ,str) or typ.strip().casefold() not in allowed: raise ValueError(f"provider 节点 {i} type 无效")
def validate_provider_payload(payload):
    if not isinstance(payload,str) or len(payload.encode())<20: raise ValueError("provider 响应过短")
    if yaml is None: raise RuntimeError("缺少 PyYAML，拒绝把字符串检查当作配置解析")
    try: data=yaml.safe_load(payload)
    except Exception as exc: raise ValueError(f"provider YAML 解析失败: {exc}")
    if not isinstance(data,dict) or not isinstance(data.get("proxies"),list): raise ValueError("provider 缺少有效 proxies 列表")
    _validate_nodes(data["proxies"])
    return {"bytes":len(payload.encode()),"sha256":hashlib.sha256(payload.encode()).hexdigest(),"proxies":len(data["proxies"])}
def refresh_provider(target_path,fetch,validate=validate_provider_payload,reload=None,kernel_validate=None):
    """跨进程串行刷新；所有校验完成后才发布，reload失败原子恢复并复核旧配置。"""
    with _path_lock(target_path), _file_lock(target_path):
        old=None
        if os.path.exists(target_path):
            with open(target_path,"rb") as fh: old=fh.read()
        payload=fetch(); info=validate(payload)
        if not isinstance(info,dict): raise ValueError("provider validate 必须返回 dict")
        if kernel_validate is not None and kernel_validate(payload) is not True: raise ValueError("mihomo provider 校验失败")
        new_bytes=payload.encode("utf-8"); backup=target_path+".bak"
        if old is not None: _atomic_bytes(backup,old)
        try:
            _atomic_bytes(target_path,new_bytes)
            if reload is not None and reload() is not True: raise RuntimeError("mihomo reload 失败")
        except Exception as exc:
            if old is not None:
                _atomic_bytes(target_path,old); rollback_ok=False; rollback_error=None
                if reload is not None:
                    try: rollback_ok=reload() is True
                    except Exception as e: rollback_error=str(e)
                status="rolled_back" if rollback_ok or reload is None else "rollback_reload_unverified"
            else: status="new_install_failed_unrecoverable"
            raise RuntimeError(f"{exc}; status={status}") from exc
        return {"changed":old!=new_bytes,**info,"backup":backup if old is not None else None,"reload_ok":True}
