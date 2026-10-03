"""个人出海生命周期；只操作独立内核，不触碰业务内核。"""
import subprocess
import time
from pathlib import Path
from .kernel_control import PERSONAL_EXE, control_lock, is_halted, stop_personal_kernel
from .personal_route_state import set_desired

PERSONAL_DIR = Path(r'D:\Program Files\AgentProxyHub\personal')
PERSONAL_CONFIG = PERSONAL_DIR / 'config.yaml'


def _running():
    script = ("@(Get-CimInstance Win32_Process -Filter \"Name='mihomo.exe'\" | "
              "Where-Object ExecutablePath -eq '" + PERSONAL_EXE.replace("'", "''") + "') | "
              "Select-Object ProcessId,ExecutablePath | ConvertTo-Json -Compress")
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                            capture_output=True, text=True, timeout=8)
    if result.returncode:
        raise RuntimeError('personal_process_probe_failed')
    return bool(result.stdout.strip() and result.stdout.strip() not in ('null', '[]'))


_STATUS_CACHE = None
_STATUS_AT = 0.0


def status(force=False):
    """短缓存共享控制器读数；不为网页轮询启动PowerShell。"""
    global _STATUS_CACHE, _STATUS_AT
    with control_lock():
        if not force and _STATUS_CACHE is not None and time.monotonic() - _STATUS_AT < 5:
            return dict(_STATUS_CACHE)
        from .tun_controller import TunController
        state = TunController(PERSONAL_CONFIG).status()
        active = state.get('tun_enabled') if state.get('ok') else None
        # 控制器不可达时才查进程；不把失联但仍运行的内核当成关闭。
        running = True if state.get('ok') else _running()
        if not running:
            active = False
        _STATUS_CACHE = {'controller': state, 'desired_on': _desired(),
                         'personal_executable': PERSONAL_EXE, 'process_running': running,
                         'active': active, 'known': active is not None}
        _STATUS_AT = time.monotonic()
        return dict(_STATUS_CACHE)


def toggle():
    """在同一可重入跨进程锁内决定方向、执行、确认。"""
    with control_lock():
        before = status(force=True)
        if not before['known']:
            return {'ok': False, 'code': 'personal_route_state_unknown', 'state': before}
        result = stop() if before['active'] else start()
        after = status(force=True)
        return {**result, 'ok': bool(result.get('ok') and after['known'] and after['active'] != before['active']),
                'state': after}


def _desired():
    from .personal_route_state import desired_on
    return desired_on()


def start():
    with control_lock():
        if is_halted():
            return {'ok': False, 'code': 'manual_halt', 'label': '停止內核'}
        if not PERSONAL_CONFIG.exists():
            return {'ok': False, 'code': 'personal_config_missing'}
        import yaml
        try:
            config = yaml.safe_load(PERSONAL_CONFIG.read_text(encoding='utf-8-sig')) or {}
        except (OSError, ValueError, yaml.YAMLError):
            return {'ok': False, 'code': 'personal_config_invalid'}
        if config.get('tun', {}).get('enable') is not True:
            return {'ok': False, 'code': 'personal_config_not_ready', 'verification': 'tun_disabled_candidate'}
        if _running():
            from .tun_controller import TunController
            state = TunController(PERSONAL_CONFIG).status()
            if state.get('tun_enabled') is True:
                set_desired(True)
                return {'ok': True, 'code': 'personal_already_running', 'label': '出海展開中'}
            return {'ok': False, 'code': 'personal_process_not_ready', 'verification': 'controller_tun_not_enabled'}
        set_desired(True)
        try:
            subprocess.Popen([PERSONAL_EXE, '-d', str(PERSONAL_DIR), '-f', str(PERSONAL_CONFIG)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as exc:
            set_desired(False)
            return {'ok': False, 'code': 'personal_start_failed', 'error': type(exc).__name__}
    from .tun_controller import TunController
    controller = TunController(PERSONAL_CONFIG)
    deadline = time.monotonic() + 8
    state = controller.status()
    while time.monotonic() < deadline and state.get('tun_enabled') is not True:
        time.sleep(0.25)
        state = controller.status()
    if state.get('tun_enabled') is True:
        return {'ok': True, 'code': 'personal_started', 'label': '出海展開中',
                'verification': 'controller_tun_enabled'}
    set_desired(False)
    stop_personal_kernel()
    return {'ok': False, 'code': 'personal_start_unverified',
            'verification': 'controller_tun_not_enabled', 'controller': state}


def stop():
    from .personal_route_state import close_personal
    result = close_personal()
    return {**result, 'label': '出海介入'}
