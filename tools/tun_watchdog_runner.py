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


def tcp_probe(host, port, timeout=2):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def collect(controller, baseline_ports):
    state = controller.status()
    enabled = state.get('tun_enabled')
    halted = is_halted()
    if halted or enabled is not True:
        return Evidence(bool(state.get('ok')), True, True, True, True,
                        enabled is True, halted), state
    # TCP到公网IP不依赖DNS；仅检查上线前本来可用的本地服务，不把未启动服务误判断网。
    direct_ok = tcp_probe('223.5.5.5', 53)
    local_ok = all(tcp_probe('127.0.0.1', p) for p in baseline_ports)
    # DNS查询必须有限时，避免Windows getaddrinfo阻塞整个保护循环。
    import subprocess
    probe = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
                            "Resolve-DnsName www.baidu.com -DnsOnly -QuickTimeout -ErrorAction Stop | Out-Null"],
                           capture_output=True, timeout=5)
    return Evidence(bool(state.get('ok')), probe.returncode == 0, direct_ok,
                    True, local_ok, True, halted), state


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--interval', type=float, default=5)
    args = parser.parse_args()
    if args.interval < 3:
        parser.error('interval must be at least 3 seconds')
    controller = TunController()
    baseline = [p for p in (8001, 8045, 8767) if tcp_probe('127.0.0.1', p)]
    dog = TunWatchdog(controller.disable_tun)
    stop = threading.Event()
    try:
        while True:
            try:
                evidence, state = collect(controller, baseline)
                decision = dog.observe(evidence)
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
