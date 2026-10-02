"""人工急停只管理 APH 自有内核；不借用第三方服务或提升权限。"""
import json
import os
import subprocess
import threading
from pathlib import Path

# 仅覆盖同一适配器进程内的 start/stop 竞态；跨进程互斥仍需特权服务侧实现。
_CONTROL_LOCK = threading.RLock()


def control_lock():
    return _CONTROL_LOCK


HALT_FILE = Path(r'D:\ProgramData\AgentProxyHub\control\manual-halt.json')
OWNED_EXE = r'D:\Program Files\AgentProxyHub\bin\mihomo.exe'
PERSONAL_EXE = r'D:\Program Files\AgentProxyHub\personal\mihomo.exe'


def stop_personal_kernel():
    """日常关闭出海：只停个人内核，不设总急停、不改系统代理或业务进程。"""
    with control_lock():
        command = _stop_command((PERSONAL_EXE,))
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
                                capture_output=True, timeout=20)
        return {'ok': result.returncode == 0, 'business_kernel_changed': False,
                'code': 'personal_kernel_stopped' if result.returncode == 0 else 'personal_stop_failed'}


def _stop_command(paths):
    # 路径只由模块内常量提供，调用方不能传任意进程名。
    allowed = {OWNED_EXE, PERSONAL_EXE}
    if not paths or any(path not in allowed for path in paths):
        raise ValueError('unowned_executable')
    literals = ','.join("'" + path + "'" for path in paths)
    return ("$ErrorActionPreference='Stop'\n$owned=@(" + literals + ")\n"
            "$targets=Get-CimInstance Win32_Process -Filter \"Name='mihomo.exe'\" | "
            "Where-Object {$_.ExecutablePath -in $owned}\n"
            "foreach($p in $targets){Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop}\n"
            "$remaining=@(Get-CimInstance Win32_Process -Filter \"Name='mihomo.exe'\" | "
            "Where-Object {$_.ExecutablePath -in $owned})\n"
            "if($remaining.Count -gt 0){throw 'owned_kernel_still_running'}\n")


def is_halted():
    return HALT_FILE.exists()


def set_halt(enabled):
    HALT_FILE.parent.mkdir(parents=True, exist_ok=True)
    if enabled:
        temporary = HALT_FILE.with_suffix('.tmp')
        temporary.write_text(json.dumps({'manual_halt': True}), encoding='utf-8')
        os.replace(temporary, HALT_FILE)
    elif HALT_FILE.exists():
        # 保留历史文件，只将有效闩锁移到非生效审计文件。
        os.replace(HALT_FILE, HALT_FILE.with_suffix('.released.json'))


def emergency_stop():
    with control_lock():
        set_halt(True)
        return _emergency_stop_locked()


def _emergency_stop_locked():
    # 白名单按 executable 精确匹配，绝不 taskkill /im mihomo.exe。
    command = _stop_command((OWNED_EXE, PERSONAL_EXE)) + r'''
# 用户主动急停：取消当前用户系统代理及PAC；不修改第三方网卡、DNS和路由。
Set-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings' -Name ProxyEnable -Value 0
Set-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings' -Name AutoConfigURL -Value ''
'''
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command], capture_output=True, timeout=20)
    return {'ok': result.returncode == 0, 'manual_halt': True,
            'code': 'owned_kernel_stopped' if result.returncode == 0 else 'emergency_stop_failed',
            'error': None if result.returncode == 0 else '检查权限及本地急停日志；闩锁仍保持，禁止自动复活',
            'third_party_kernels_changed': False}
