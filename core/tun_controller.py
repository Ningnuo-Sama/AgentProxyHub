"""本机控制器撤销TUN与脱敏状态；不使用环境代理，不开启TUN。"""
import json
import urllib.request
import urllib.error
from pathlib import Path
from core.personal_route import runtime_controller_auth

RUNTIME_CONFIG = Path(r'D:\Program Files\AgentProxyHub\config\config.yaml')


class TunController:
    def __init__(self, config_path=RUNTIME_CONFIG, opener=None):
        self.base, self.headers = runtime_controller_auth(config_path)
        # 防止系统代理或 HTTP_PROXY 让控制器请求走海外/形成自环。
        self.opener = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def request(self, method, path, body=None):
        if method.upper() != 'GET':
            from core.kernel_control import control_lock
            with control_lock():
                return self._request_unlocked(method, path, body)
        return self._request_unlocked(method, path, body)

    def _request_unlocked(self, method, path, body=None):
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

    def reload_disabled_snapshot(self, snapshot_path):
        """控制器仍存活时加载已核对的关闭TUN快照；只接受私有回退目录。"""
        import yaml
        from core.personal_route import fixed_listener_map
        path = Path(snapshot_path).resolve()
        root = Path(r'D:\ProgramData\AgentProxyHub\backups').resolve()
        if not path.is_relative_to(root):
            return {'ok': False, 'code': 'backup_path_required'}
        try:
            snapshot = yaml.safe_load(path.read_text(encoding='utf-8-sig'))
            runtime = yaml.safe_load(RUNTIME_CONFIG.read_text(encoding='utf-8-sig'))
            if (snapshot.get('tun') or {}).get('enable', False):
                return {'ok': False, 'code': 'snapshot_tun_must_be_disabled'}
            if (fixed_listener_map(snapshot) != fixed_listener_map(runtime) or
                    snapshot.get('listeners') != runtime.get('listeners')):
                return {'ok': False, 'code': 'snapshot_business_mapping_mismatch'}
            self.request('PUT', '/configs?force=true', {'path': str(path)})
            after = self.status()
            return {'ok': after.get('ok') and after.get('tun_enabled') is False,
                    'action': 'reload_disabled_snapshot', 'business_kernel_stopped': False}
        except urllib.error.HTTPError as exc:
            return {'ok': False, 'code': 'snapshot_reload_denied' if exc.code == 400 else 'snapshot_reload_failed',
                    'http_status': exc.code, 'error': type(exc).__name__}
        except Exception as exc:
            return {'ok': False, 'code': 'snapshot_reload_failed', 'error': type(exc).__name__}

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
