"""本地 TUN 故障判定与有限撤销，不联网调用模型，不自动开启/重启内核。"""
from dataclasses import dataclass
from typing import Callable


@dataclass
class Evidence:
    controller_ok: bool
    dns_ok: bool
    direct_ok: bool
    proxy_ok: bool
    local_services_ok: bool
    tun_enabled: bool | None
    manual_halt: bool = False


class TunWatchdog:
    """部署方提供真实独立探针和撤销回调；本类不冒充常驻服务。"""
    def __init__(self, rollback: Callable[[], dict], threshold: int = 3):
        if threshold < 1:
            raise ValueError('invalid_threshold')
        self.rollback = rollback
        self.threshold = threshold
        self.failures = 0
        self.latched = False

    def observe(self, evidence: Evidence) -> dict:
        if evidence.manual_halt:
            self.latched = True
            return {'action': 'respect_manual_halt', 'restart': False}
        if evidence.tun_enabled is None:
            return {'action': 'controller_unknown', 'ok': False, 'restart': False}
        if evidence.tun_enabled is False:
            self.failures = 0
            return {'action': 'tun_off', 'restart': False}
        if self.latched:
            return {'action': 'await_manual_enable', 'restart': False}
        # 单纯海外节点失败不算整机断网；由节点健康管理处理，不能急停全部业务。
        healthy = (evidence.controller_ok and evidence.dns_ok and
                   evidence.direct_ok and evidence.local_services_ok)
        self.failures = 0 if healthy else self.failures + 1
        if self.failures < self.threshold:
            return {'action': 'healthy' if healthy else 'observe', 'failures': self.failures}
        # 先闩锁再调用，即使撤销异常也不产生无限重试/重连风暴。
        self.latched = True
        try:
            result = self.rollback()
            return {'action': 'rollback', 'ok': bool(result.get('ok')), 'restart': False}
        except Exception as exc:
            return {'action': 'rollback_failed', 'ok': False,
                    'error': type(exc).__name__, 'restart': False}
