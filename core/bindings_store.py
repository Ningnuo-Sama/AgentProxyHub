#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bindings.json 的并发安全读写入口，兼容 CloakMulti 的平面 JSON。"""
import contextlib, copy, json, os, time
from typing import Any, Dict, Optional
try:
    import msvcrt
except ImportError:
    msvcrt = None
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__))); DATA_DIR=os.path.join(ROOT,"data")
BINDINGS_FILE=os.path.join(DATA_DIR,"bindings.json"); LOCK_FILE=os.path.join(DATA_DIR,"bindings.lock")
REVISION_FILE=os.path.join(DATA_DIR,"bindings.revision"); JOURNAL_FILE=os.path.join(DATA_DIR,"bindings.journal")
PORT_RANGES=((21001,21080),(22001,22045))
def _valid_port(port): return any(a<=port<=b for a,b in PORT_RANGES)
def _read_json(path):
    with open(path,"r",encoding="utf-8") as f: value=json.load(f)
    if not isinstance(value,dict): raise ValueError(f"{os.path.basename(path)} 必须是对象")
    return value
def _read_unlocked(): return _read_json(BINDINGS_FILE) if os.path.exists(BINDINGS_FILE) else {}
def _read_revision_unlocked():
    if not os.path.exists(REVISION_FILE): return 0
    with open(REVISION_FILE,"r",encoding="ascii") as f: raw=f.read().strip()
    if not raw.isdigit(): raise ValueError("bindings revision 损坏，拒绝写入")
    return int(raw)
def _recover_unlocked():
    if not os.path.exists(JOURNAL_FILE): return
    journal=_read_json(JOURNAL_FILE); data=journal.get("data"); revision=journal.get("revision")
    if not isinstance(data,dict) or not isinstance(revision,int) or revision<1: raise ValueError("bindings journal 损坏")
    # journal 已完整落盘时，恢复两个兼容文件；恢复过程仍在锁内。
    _atomic_text(BINDINGS_FILE,data); _atomic_text(REVISION_FILE,str(revision)+"\n"); os.unlink(JOURNAL_FILE)
@contextlib.contextmanager
def locked():
    os.makedirs(DATA_DIR,exist_ok=True)
    with open(LOCK_FILE,"a+b") as f:
        if msvcrt: f.seek(0); msvcrt.locking(f.fileno(),msvcrt.LK_LOCK,1)
        try: _recover_unlocked(); yield
        finally:
            if msvcrt: f.seek(0); msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)
def read():
    with locked(): return copy.deepcopy(_read_unlocked())
def read_with_revision():
    with locked(): return copy.deepcopy(_read_unlocked()),_read_revision_unlocked()
def _atomic_text(path,value):
    tmp=f"{path}.{os.getpid()}.tmp"
    with open(tmp,"w",encoding="utf-8",newline="\n") as f:
        if isinstance(value,dict): json.dump(value,f,ensure_ascii=False,indent=2)
        else: f.write(value)
        f.write("\n"); f.flush(); os.fsync(f.fileno())
    os.replace(tmp,path)
def _commit(data,new_revision):
    # 单一原子 journal 是提交事实；两个兼容文件可在崩溃后由下次读恢复。
    _atomic_text(JOURNAL_FILE,{"data":data,"revision":new_revision})
    _atomic_text(BINDINGS_FILE,data); _atomic_text(REVISION_FILE,str(new_revision)+"\n")
    os.unlink(JOURNAL_FILE)
    if _read_unlocked()!=data or _read_revision_unlocked()!=new_revision: raise IOError("bindings 回读校验失败")
def write(data:Dict[str,Any],expected_revision:Optional[int]=None):
    if not isinstance(data,dict): raise ValueError("bindings 必须是对象")
    for key in data:
        if key=="__meta__" or not _valid_port(int(key)): raise ValueError(f"非法端口: {key}")
    with locked():
        # 现有账本损坏时禁止用新内容静默覆盖。
        _read_unlocked()
        current=_read_revision_unlocked()
        if expected_revision is not None and current!=expected_revision: raise RuntimeError(f"revision 冲突: expected={expected_revision}, actual={current}")
        new=current+1; _commit(data,new); return new
def bind(profile,port,note=""):
    if not profile: raise ValueError("profile 不能为空")
    port=int(port)
    if not _valid_port(port): raise ValueError("端口必须位于 21001-21080 或 22001-22045")
    with locked():
        data=_read_unlocked(); old=data.get(str(port))
        if old and old.get("profile")!=profile: raise RuntimeError(f"端口 {port} 已绑定给环境 [{old.get('profile')}]")
        data[str(port)]={"profile":profile,"bound_at":time.strftime("%Y-%m-%d %H:%M:%S"),"note":note}
        rev=_read_revision_unlocked()+1; _commit(data,rev); return {"data":copy.deepcopy(data),"revision":rev}
