"""个人内核启动前只读门禁；通过不代表防环或业务无干扰已验收。"""
from pathlib import PureWindowsPath
from core.personal_tun_isolation import FIXED_PORTS

BUSINESS_EXE = PureWindowsPath(r'D:\Program Files\AgentProxyHub\bin\mihomo.exe')


def check_preflight(config, *, executable, manual_halt, business_tun, occupied_ports,
                    emergency_stop_covers_personal=False):
    """输入均为调用方现场证据；任一缺失关键保护则拒绝启动。"""
    if manual_halt:
        return {'ok': False, 'code': 'manual_halt'}
    if business_tun is not False:
        return {'ok': False, 'code': 'business_tun_not_confirmed_off'}
    if PureWindowsPath(executable) == BUSINESS_EXE:
        return {'ok': False, 'code': 'shared_executable_identity'}
    from core.kernel_control import PERSONAL_EXE
    if PureWindowsPath(executable) != PureWindowsPath(PERSONAL_EXE):
        return {'ok': False, 'code': 'personal_executable_not_allowlisted'}
    if not emergency_stop_covers_personal:
        return {'ok': False, 'code': 'personal_emergency_stop_not_installed'}
    if config.get('listeners') or any(config.get(k) for k in
                                    ('port', 'socks-port', 'mixed-port', 'redir-port', 'tproxy-port')):
        return {'ok': False, 'code': 'unexpected_listeners'}
    controller = config.get('external-controller', '')
    try:
        host, port = controller.rsplit(':', 1)
        port = int(port)
    except (ValueError, AttributeError):
        return {'ok': False, 'code': 'invalid_controller'}
    if host != '127.0.0.1' or not config.get('secret') or not 1 <= port <= 65535:
        return {'ok': False, 'code': 'unsafe_controller'}
    if port in FIXED_PORTS or port in (21909, 39999) or port in occupied_ports:
        return {'ok': False, 'code': 'controller_conflict'}
    return {'ok': True, 'code': 'preflight_only', 'started': False,
            'loop_prevention_verified': False, 'gemini_noninterference_verified': False}
