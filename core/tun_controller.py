"""本机控制器撤销TUN与脱敏状态；不使用环境代理，不开启TUN。"""
import json
import urllib.request
from pathlib import Path
from core.personal_route import runtime_controller_auth

RUNTIME_CONFIG = Path(r'D:\Program Files\AgentProxyHub\config\config.yaml')


class TunController:
    def __init__(self, config_path=RUNTIME_CONFIG, opener=None):
        self.base, self.headers = runtime_controller_auth(config_path)
        # 防止系统代理或 HTTP_PROXY 让控制器请求走海外/形成自环。
        self.opener = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def request(self, method, path, body=None):
        data = None if body is None else json.dumps(body).encode('utf-8')
        request = urllib.request.Request(self.base + path, data=data, method=method,
                                         headers={**self.headers, 'Content-Type': 'application/json'})
        with self.opener.open(request, timeout=3) as response:
            raw = response.read()
            return json.loads(raw) if raw else {}

    def status(self):
        try:
            config = self.request('GET', '/configs')
            return {'ok': True, 'tun_enabled': bool((config.get('tun') or {}).get('enable')),
                    'mode': config.get('mode'), 'source': 'live_controller'}
        except Exception as exc:
            return {'ok': False, 'tun_enabled': None, 'error': type(exc).__name__}

    def disable_tun(self):
        """仅撤销个人TUN，不改125个listener，不停止业务内核。"""
        try:
            before = self.status()
            if before.get('ok') and before['tun_enabled'] is False:
                return {'ok': True, 'action': 'already_disabled', 'business_kernel_stopped': False}
            self.request('PATCH', '/configs', {'tun': {'enable': False}})
            after = self.status()
            return {'ok': after.get('ok') and after.get('tun_enabled') is False,
                    'action': 'disable_tun', 'business_kernel_stopped': False}
        except Exception as exc:
            return {'ok': False, 'action': 'disable_tun_failed', 'error': type(exc).__name__}
