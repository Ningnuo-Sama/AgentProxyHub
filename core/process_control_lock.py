"""同一Windows用户/权限范围内的协作控制锁；所有启停入口必须主动使用。"""
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path

_THREAD_LOCK = threading.RLock()
_LOCAL = threading.local()
LOCK_FILE = Path(r'D:\ProgramData\AgentProxyHub\control\kernel-control.lock')


@contextmanager
def process_control_lock(path=None, timeout=25):
    """可重入的一字节文件锁；超时拒绝操作，进程退出由系统释放。"""
    if os.name != 'nt':
        raise RuntimeError('windows_control_lock_required')
    import msvcrt
    target = Path(path or LOCK_FILE)
    deadline = time.monotonic() + max(0, timeout)
    if not _THREAD_LOCK.acquire(timeout=max(0, timeout)):
        raise TimeoutError('kernel_control_thread_lock_busy')
    try:
        depth = getattr(_LOCAL, 'depth', 0)
        if depth:
            if getattr(_LOCAL, 'path', None) != str(target):
                raise RuntimeError('nested_control_lock_path_mismatch')
            _LOCAL.depth += 1
            try:
                yield
            finally:
                _LOCAL.depth -= 1
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('a+b', buffering=0) as handle:
            if handle.seek(0, 2) == 0:
                handle.write(b'0')
            while True:
                handle.seek(0)
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError('kernel_control_lock_busy')
                    time.sleep(0.05)
            _LOCAL.depth = 1
            _LOCAL.path = str(target)
            try:
                yield
            finally:
                _LOCAL.depth = 0
                _LOCAL.path = None
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    finally:
        _THREAD_LOCK.release()
