#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""aphub_lock —— AgentProxyHub 跨进程账本锁的**唯一实现**（单点权威）。

为什么要抽出来
--------------
`bindings.json` / `upstreams.json` 是**多写方**账本：多个 MCP 实例（每个 Agent 客户端
人手一个）+ CloakMulti GUI 会并发做 read-modify-write。原先两侧各自实现锁：

  * `mcp/server.py`      用 `msvcrt.locking(LK_LOCK, 1)`
  * `CloakMulti/aphub.py` 只用 `threading.Lock()`（仅进程内）

两侧语义不一致就是 T2 报告里"非对称锁契约"的形态。本模块把它们收敛到**同一套语义**。

关于 `LK_LOCK` 的事实订正（t29 实测，务必先读）
---------------------------------------------
t20 曾据**同进程**探针得出"`LK_LOCK` 不会阻塞"，那个结论是**错的**（详见
`scratch/agent-teams/mcp-lock-fix.md` §2）。实测：

  | 场景 | 结果 |
  |---|---|
  | `LK_LOCK` **跨进程**竞争 | **真的等待**（等持锁方释放，实测 ~2.0s 后取得）|
  | `LK_LOCK` **同进程**同字节再取 | 抛 `Resource deadlock avoided`（等待 ~9s 后报错）|

即"跨进程会阻塞、同进程自锁会报错"。因此本模块**不声称修了假阻塞**，
它修的是另外两件真问题：

  1. **`LK_LOCK` 没有超时** —— 持锁方卡死时，写方会**无限期挂住**；
  2. **两侧没有共同的失败语义** —— 超时后是报错还是降级，原先未定义。

统一语义（本模块即契约）
------------------------
* 获取：`LK_NBLCK` 非阻塞试取 + 20ms 自旋，直到 `timeout_s`；跨进程真阻塞、同进程不误判死锁。
* 超时：抛 `LockTimeout`，**绝不带锁失败后强写**。
* 调用方（写方）必须 fail-closed：放弃本次写入 + 告警（见各写方的 `except LockTimeout`）。
* `timeout_s=None` 可显式要求无限等待（仅供确知不会死锁的场景，默认不用）。
* 可重入：同一线程嵌套获取同一路径时按深度计数，不会自锁。

用法
----
    from core.aphub_lock import bindings_lock, LockTimeout
    try:
        with bindings_lock(DATA_DIR):
            ...            # read-modify-write
    except LockTimeout as e:
        return {"success": False, "code": "lock_timeout", "error": str(e)}   # 不改账本
"""
from __future__ import annotations

import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path

try:  # Windows 专用；非 Windows 退化为仅线程锁
    import msvcrt
except ImportError:  # pragma: no cover
    msvcrt = None

__all__ = ["LockTimeout", "file_lock", "bindings_lock", "upstreams_lock",
           "LOCK_TIMEOUT_S", "LOCK_POLL_S", "LOCK_SUFFIX", "UPSTREAMS_LOCK_SUFFIX"]

# ---- 统一参数（唯一权威，勿在别处再定义一套）---------------------------------
LOCK_TIMEOUT_S = 10.0      # 获取锁的最长等待；超时即 fail-closed
LOCK_POLL_S = 0.02         # 自旋间隔
LOCK_SUFFIX = "bindings.lock"
UPSTREAMS_LOCK_SUFFIX = "upstreams.lock"

# 同进程内按「线程 + 锁文件绝对路径」记录重入深度，避免自己把自己锁死
_STATE = threading.local()


def _depth_map() -> dict:
    d = getattr(_STATE, "depth", None)
    if d is None:
        d = {}
        _STATE.depth = d
    return d


class LockTimeout(TimeoutError):
    """在 timeout_s 内未能取得跨进程锁。调用方**必须放弃写入**并告警，禁止强写。"""

    def __init__(self, path: str, timeout_s: float):
        self.path = path
        self.timeout_s = timeout_s
        super().__init__("获取账本锁超时（%.1fs）：%s —— 已放弃本次写入（fail-closed）"
                         % (timeout_s, path))


@contextmanager
def file_lock(path: str | os.PathLike, timeout_s: float | None = LOCK_TIMEOUT_S,
              poll_s: float = LOCK_POLL_S, mkdir: bool = True):
    """对 `path` 指向的锁文件做**跨进程**互斥；超时抛 `LockTimeout`。

    `timeout_s=None` 表示无限等待（显式选择，默认不用）。
    同一线程嵌套获取同一路径时按深度计数，不会自锁。
    """
    target = Path(path)
    if mkdir:
        target.parent.mkdir(parents=True, exist_ok=True)
    key = str(target.resolve()) if target.exists() else str(target.absolute())

    depth = _depth_map()
    if depth.get(key):                       # 可重入：同线程已持有
        depth[key] += 1
        try:
            yield
        finally:
            depth[key] -= 1
        return

    if msvcrt is None:                       # 非 Windows：仅保证线程内互斥
        depth[key] = 1
        try:
            yield
        finally:
            depth[key] = 0
        return

    deadline = None if timeout_s is None else (time.monotonic() + max(0.0, timeout_s))
    with open(target, "a+b") as handle:
        while True:
            try:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                if deadline is not None and time.monotonic() >= deadline:
                    raise LockTimeout(str(target), timeout_s if timeout_s else 0.0)
                time.sleep(poll_s)
        depth[key] = 1
        try:
            yield
        finally:
            depth[key] = 0
            try:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass


def bindings_lock(data_dir: str | os.PathLike, timeout_s: float | None = LOCK_TIMEOUT_S):
    """`<data_dir>/bindings.lock` 的跨进程锁 —— MCP 与 CloakMulti **共用同一把**。"""
    return file_lock(Path(data_dir) / LOCK_SUFFIX, timeout_s=timeout_s)


def upstreams_lock(data_dir: str | os.PathLike, timeout_s: float | None = LOCK_TIMEOUT_S):
    """`<data_dir>/upstreams.lock` 的跨进程锁。"""
    return file_lock(Path(data_dir) / UPSTREAMS_LOCK_SUFFIX, timeout_s=timeout_s)
