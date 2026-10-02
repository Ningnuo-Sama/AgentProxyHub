"""独立本地看门狗入口：--once只查状态，常驻模式须显式运行；不启动TUN。"""
import argparse
import json
import socket
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.kernel_control import is_halted
from core.tun_controller import TunController
from core.tun_watchdog import Evidence, TunWatchdog

RUNTIME_HALT = Path(r'D:\ProgramData\AgentProxyHub\control\manual-halt.json')


def tcp_probe(host, port, timeout=2):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def proxy_probe(controller):
    """仅探测当前PERSONAL出口是否能建立HTTPS，不暴露响应内容。"""
    try:
        request = controller.opener.open('https://www.google.com/generate_204', timeout=6)
        request.close()
        return True
    except Exception:
        return False


def collect(controller, baseline_ports):
    state = controller.status()
    enabled = state.get('tun_enabled')
    halted = is_halted()
    if halted or enabled is not True:
        return Evidence(bool(state.get('ok')), True, True, True, True,
                        enabled, halted), state
    # TCP到公网IP不依赖DNS；仅检查上线前本来可用的本地服务，不把未启动服务误判断网。
    direct_ok = tcp_probe('223.5.5.5', 53)
    local_ok = all(tcp_probe('127.0.0.1', p) for p in baseline_ports)
    # DNS查询必须有限时，避免Windows getaddrinfo阻塞整个保护循环。
    import subprocess
    try:
        probe = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
                                "Resolve-DnsName www.baidu.com -DnsOnly -QuickTimeout -ErrorAction Stop | Out-Null"],
                               capture_output=True, timeout=5)
        dns_ok = probe.returncode == 0
    except subprocess.TimeoutExpired:
        dns_ok = False
    return Evidence(bool(state.get('ok')), dns_ok, direct_ok,
                    proxy_probe(controller), local_ok, True, halted), state


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--personal', action='store_true', help='仅监护固定个人控制器21919')
    parser.add_argument('--interval', type=float, default=5)
    args = parser.parse_args()
    if args.interval < 3:
        parser.error('interval must be at least 3 seconds')
    if args.personal and not Path(r'D:\Program Files\AgentProxyHub\personal\config.yaml').exists():
        parser.error('personal configuration missing')
    personal_guard = None
    if args.personal:
        from core.kernel_control import stop_personal_kernel
        from core.personal_watchdog import PersonalControllerGuard
        controller = TunController(Path(r'D:\Program Files\AgentProxyHub\personal\config.yaml'))
        if controller.base != 'http://127.0.0.1:21919':
            parser.error('personal controller must be loopback 21919')
        personal_guard = PersonalControllerGuard(stop_personal_kernel)
    else:
        controller = TunController()
    baseline = [p for p in (8001, 8045, 8767) if tcp_probe('127.0.0.1', p)]
    # 个人模式故障退出只针对个人进程，不热重载业务配置。
    dog = TunWatchdog(stop_personal_kernel if args.personal else controller.disable_tun)
    stop = threading.Event()
    # 退出看门狗前不主动复活内核；人工闩锁由共享文件持续生效。
    if is_halted():
        print(json.dumps({'ok': True, 'code': 'manual_halt', 'decision': {'action': 'respect_manual_halt'}}, ensure_ascii=False), flush=True)
        return 0
    try:
        while True:
            try:
                if args.personal:
                    from core.personal_route_state import desired_on
                    if not desired_on():
                        state = controller.status()
                        result = stop_personal_kernel() if state.get('tun_enabled') is True else None
                        print(json.dumps({'controller': state, 'decision': {'action': 'personal_desired_off', 'restart': False, 'stop_result': result}}, ensure_ascii=False), flush=True)
                        if args.once:
                            return 0
                        stop.wait(args.interval)
                        continue
                evidence, state = collect(controller, baseline)
                decision = dog.observe(evidence)
                if personal_guard is not None:
                    guard_decision = personal_guard.observe(state, manual_halt=is_halted())
                    if guard_decision['action'] == 'stop_personal_on_controller_loss':
                        decision = guard_decision
                print(json.dumps({'controller': state, 'decision': decision}, ensure_ascii=False), flush=True)
            except Exception as exc:
                # 未知采样异常不能擅自停掉业务；明示监护降级，不无限吞错。
                print(json.dumps({'ok': False, 'code': 'probe_failed', 'error': type(exc).__name__}), flush=True)
                return 1
            if args.once:
                return 0
            stop.wait(args.interval)
    except KeyboardInterrupt:
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
