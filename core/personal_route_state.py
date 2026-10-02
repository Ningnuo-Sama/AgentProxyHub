"""个人出海意图持久化；意图不代表内核实际状态。损坏或缺失默认关闭。"""
import json
import os
import tempfile
from pathlib import Path

STATE_FILE = Path(r'D:\ProgramData\AgentProxyHub\control\personal-route.json')


def desired_on(path=STATE_FILE):
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        return data.get('desired_on') is True
    except (OSError, ValueError, TypeError, AttributeError):
        return False


def set_desired(enabled, path=STATE_FILE):
    if not isinstance(enabled, bool):
        raise ValueError('boolean_required')
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='personal-route-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump({'version': 1, 'desired_on': enabled}, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def close_personal():
    from core.kernel_control import control_lock, stop_personal_kernel
    with control_lock():
        set_desired(False)
        result = stop_personal_kernel()
        return {**result, 'desired_on': False}
