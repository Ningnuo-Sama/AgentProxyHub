#!/usr/bin/env python3
# EVA H5 本地适配层：只在 loopback 提供脱敏状态和已登记任务，不暴露凭据。
import json, os, sys, urllib.request, time
from pathlib import Path
from urllib.parse import parse_qs, quote
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault('APHUB_DATA_DIR', r'D:\Program Files\AgentProxyHub\data')
from mcp.server import tool_jingguanjia_orphan, tool_get_profile_bindings, tool_autonomy_action, tool_channel_health, tool_kernel_recovery, get_nodes_data
from core.model_router import complete, status as model_status
from core.alert_dispatch import notify_all

MIHOMO_CONTROLLER = 'http://127.0.0.1:21909'
MIHOMO_HEADERS = {'Authorization': 'Bearer f8fac3fd419ea0b765a238e0'}
UPSTREAMS = {
    'flow': 'http://127.0.0.1:8001/health',
    'gemini': 'http://127.0.0.1:8045/health',
    'viking': 'http://127.0.0.1:18790/health',
    'pet': 'http://127.0.0.1:8766/health',
}
ALLOWED_TASKS = {'scan_orphans', 'audit_log', 'clean_all_safe_orphans'}
ALLOWED_COMMANDS = {'health', 'recovery', 'autonomy', 'bindings', 'quota', 'models', 'usage'}
LOG_SOURCES = {
    'mihomo': Path(r'D:\Program Files\AgentProxyHub\logs\bridge.log'),
    'hermes': Path(r'D:\Program Files (x86)\hermes\logs\gateway.log'),
    'hermes_watchdog': Path(r'D:\Program Files (x86)\hermes\logs\gateway-watchdog.log'),
    'usage': Path(r'D:\Program Files\AgentProxyHub\data\model_usage.jsonl'),
    'autonomy': Path(r'D:\Program Files\AgentProxyHub\data\autonomy_events.jsonl'),
}

def read_log_source(name, limit=80):
    path = LOG_SOURCES.get(name)
    if not path or not path.exists(): return {'name': name, 'available': False, 'lines': []}
    try:
        lines = path.read_text(encoding='utf-8', errors='replace').splitlines()
        return {'name': name, 'available': True, 'path': str(path), 'lines': lines[-max(1, min(int(limit), 200)):]}
    except OSError as exc:
        return {'name': name, 'available': False, 'error': type(exc).__name__, 'lines': []}

def read_driver_cards():
    bindings = tool_get_profile_bindings({})
    quota = {a.get('email'): a for a in read_antigravity_quota().get('accounts', [])}
    cards = []
    for item in bindings.get('antigravity_account_stickiness', []):
        email = item.get('account')
        models = (quota.get(email) or {}).get('models') or []
        cards.append({'account': email, 'port': item.get('port'), 'node_name': item.get('node_name'), 'proxy_id': item.get('proxy_id'), 'models': models, 'mapping_source': 'antigravity_account_stickiness + local quota'})
    return {'ok': True, 'cards': cards, 'count': len(cards), 'secrets_excluded': True}

def read_antigravity_quota():
    root = Path(r'C:\Users\1\.antigravity_tools\accounts')
    rows = []
    if not root.exists(): return {'ok': False, 'code': 'quota_source_missing', 'accounts': []}
    for path in root.glob('*.json'):
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            models = data.get('quota', {}).get('models', [])
            rows.append({'id': data.get('id'), 'email': data.get('email'), 'models': [
                {'name': m.get('name'), 'display_name': m.get('display_name'), 'percentage': m.get('percentage'), 'reset_time': m.get('reset_time')}
                for m in models if isinstance(m, dict)
            ]})
        except (OSError, ValueError, TypeError):
            continue
    return {'ok': True, 'source': str(root), 'accounts': rows, 'account_count': len(rows), 'secrets_excluded': True}

def mihomo_get(path, timeout=6):
    request = urllib.request.Request(MIHOMO_CONTROLLER + path, headers=MIHOMO_HEADERS)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode('utf-8', 'replace'))

def mihomo_put(path, payload, timeout=8):
    raw = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    request = urllib.request.Request(MIHOMO_CONTROLLER + path, data=raw, method='PUT', headers={**MIHOMO_HEADERS, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read().decode('utf-8', 'replace')
        return json.loads(body) if body else {'ok': True}

def _bytes_per_second(now, previous, interval):
    if not previous or interval <= 0: return 0
    return max(0, now - previous) / interval

def read_gateway_state():
    try:
        proxies = mihomo_get('/proxies').get('proxies', {})
        connections = mihomo_get('/connections')
        active = []
        overseas = direct = {'upload': 0, 'download': 0, 'connections': 0}
        for c in connections.get('connections', []):
            meta = c.get('metadata') or {}
            chain = ' '.join(c.get('chains') or [])
            row = {'inbound_port': meta.get('inboundPort'), 'host': meta.get('host'), 'chain': chain, 'upload': c.get('upload', 0), 'download': c.get('download', 0)}
            active.append(row)
            bucket = direct if chain.upper() == 'DIRECT' or not chain else overseas
            bucket['upload'] += row['upload']; bucket['download'] += row['download']; bucket['connections'] += 1
        groups = [{'name': n, 'type': v.get('type'), 'now': v.get('now'), 'alive': v.get('alive'), 'all_count': len(v.get('all', []))} for n,v in proxies.items() if v.get('type') in ('Selector','URLTest','Fallback','LoadBalance')]
        return {'ok': True, 'source': MIHOMO_CONTROLLER, 'groups': groups, 'traffic': {'total': {'upload': connections.get('uploadTotal', 0), 'download': connections.get('downloadTotal', 0)}, 'overseas': overseas, 'direct': direct}, 'connections': active, 'generated_at': time.time()}
    except Exception as exc:
        return {'ok': False, 'source': MIHOMO_CONTROLLER, 'error': type(exc).__name__, 'traffic': {'total': {}, 'overseas': {}, 'direct': {}}, 'groups': [], 'connections': []}

def probe(url):
    try:
        with urllib.request.urlopen(url, timeout=4) as r:
            return {'ok': r.status == 200, 'status': r.status, 'body': json.loads(r.read().decode('utf-8', 'replace'))}
    except Exception as e:
        return {'ok': False, 'status': 0, 'error': type(e).__name__}

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_): pass
    def send_json(self, status, payload):
        raw = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        origin = self.headers.get('Origin', '')
        allowed_origin = origin if origin in {'http://127.0.0.1:8768', 'http://localhost:8768', 'http://127.0.0.1:43121'} else 'http://127.0.0.1:8768'
        self.send_header('Access-Control-Allow-Origin', allowed_origin)
        self.send_header('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers(); self.wfile.write(raw)
    def do_OPTIONS(self): self.send_json(204, {})
    def do_GET(self):
        path = urlparse(self.path).path
        if path == '/health': return self.send_json(200, {'ok': True, 'service': 'eva-h5-adapter'})
        if path == '/api/services':
            return self.send_json(200, {'ok': True, 'services': {k: probe(v) for k,v in UPSTREAMS.items()}, 'cliproxyapi': 'excluded'})
        if path == '/api/bindings': return self.send_json(200, {'ok': True, 'result': tool_get_profile_bindings({})})
        if path == '/api/audit': return self.send_json(200, {'ok': True, 'result': tool_jingguanjia_orphan({'action':'audit_log','limit':30})})
        if path == '/api/models': return self.send_json(200, model_status())
        if path == '/api/health': return self.send_json(200, tool_channel_health({}))
        if path == '/api/gateway': return self.send_json(200, read_gateway_state())
        if path == '/api/snapshot':
            health = tool_channel_health({})
            autonomy = tool_autonomy_action({'action':'status'})
            quota = read_antigravity_quota()
            from core.model_usage import usage_summary
            return self.send_json(200, {'ok': True, 'generated_at': __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(), 'health': health, 'autonomy': autonomy, 'quota': quota, 'usage': usage_summary()})
        if path == '/api/autonomy': return self.send_json(200, tool_autonomy_action({'action':'status'}))
        if path == '/api/logs':
            query = parse_qs(urlparse(self.path).query)
            names = [x.strip() for x in (query.get('sources') or query.get('source') or [''])[0].split(',') if x.strip()] or list(LOG_SOURCES)
            return self.send_json(200, {'ok': True, 'sources': [read_log_source(name, 100) for name in names]})
        if path == '/api/usage':
            from core.model_usage import usage_summary
            return self.send_json(200, usage_summary())
        if path == '/api/quota': return self.send_json(200, read_antigravity_quota())
        if path == '/api/driver-cards': return self.send_json(200, read_driver_cards())
        if path == '/api/topology':
            health = tool_channel_health({})
            autonomy = tool_autonomy_action({'action':'status'})
            return self.send_json(200, {'ok': True, 'nodes': [
                {'id':'aph','label':'AgentProxyHub','kind':'core','status':'online'},
                {'id':'mihomo','label':'mihomo 固定端口池','kind':'proxy','status':'online'},
                {'id':'gemini','label':'Antigravity / Gemini','kind':'model','status':health.get('channels',{}).get('gemini_antigravity',{}).get('status','unknown')},
                {'id':'flow','label':'Flow-Tools','kind':'media','status':health.get('channels',{}).get('flow_tools',{}).get('status','unknown')},
                {'id':'pet','label':'鲸管家','kind':'notify','status':health.get('channels',{}).get('jingguanjia',{}).get('status','unknown')},
                {'id':'hermes','label':'Hermes / 微信','kind':'notify','status':'configured'},
                {'id':'viking','label':'OpenViking','kind':'memory','status':health.get('channels',{}).get('openviking_gateway',{}).get('status','unknown')},
            ], 'edges': [['aph','mihomo'],['aph','gemini'],['aph','flow'],['aph','pet'],['aph','hermes'],['aph','viking']], 'autonomy': autonomy})
        return self.send_json(404, {'ok': False, 'code': 'not_found'})
    def do_POST(self):
        path = urlparse(self.path).path
        length = int(self.headers.get('Content-Length', '0'))
        try: body = json.loads(self.rfile.read(length) or b'{}')
        except Exception: body = {}
        if path == '/api/task':
            task = body.get('task')
            if task not in ALLOWED_TASKS: return self.send_json(403, {'ok': False, 'code':'task_not_allowed'})
            return self.send_json(200, {'ok': True, 'result': tool_jingguanjia_orphan({'action':task, 'limit':30})})
        if path == '/api/paid/prepare':
            return self.send_json(200, {'ok': True, 'status':'awaiting_final_user_confirmation', 'submitted':False})
        if path == '/api/wechat/prepare':
            return self.send_json(200, {'ok': True, 'target':'一帆', 'status':'prepared', 'sent':False})
        if path == '/api/notify':
            text = str(body.get('text') or '').strip()
            if not text or len(text) > 2000: return self.send_json(400, {'ok': False, 'code':'invalid_text'})
            return self.send_json(200, {'ok': True, 'delivery': notify_all(text, event_id=body.get('event_id'))})
        if path == '/api/autonomy/run_once':
            return self.send_json(200, tool_autonomy_action({'action':'run_once', 'notify': bool(body.get('notify', True))}))
        if path == '/api/recovery':
            return self.send_json(200, tool_kernel_recovery({'ports': body.get('ports') or [21001, 21008, 22002, 21909]}))
        if path == '/api/route':
            mode = str(body.get('mode') or '').strip().lower()
            if mode not in {'overseas', 'direct'}: return self.send_json(400, {'ok': False, 'code': 'invalid_route_mode'})
            group = str(body.get('group') or 'GLOBAL')
            target = 'AUTO-POOL' if mode == 'overseas' else 'DIRECT'
            try:
                result = mihomo_put('/proxies/' + quote(group, safe='') , {'name': target})
                return self.send_json(200, {'ok': True, 'mode': mode, 'group': group, 'target': target, 'result': result, 'gateway': read_gateway_state()})
            except Exception as exc:
                return self.send_json(502, {'ok': False, 'code': 'route_switch_failed', 'error': type(exc).__name__})
        if path == '/api/command':
            command = str(body.get('command') or '').strip().lower()
            if command not in ALLOWED_COMMANDS: return self.send_json(403, {'ok': False, 'code':'command_not_allowed', 'allowed': sorted(ALLOWED_COMMANDS)})
            if command == 'health': return self.send_json(200, tool_channel_health({}))
            if command == 'recovery': return self.send_json(200, tool_kernel_recovery({'ports': body.get('ports') or [21001, 21008, 22002, 21909]}))
            if command == 'autonomy': return self.send_json(200, tool_autonomy_action({'action':'run_once', 'notify': True}))
            if command == 'bindings': return self.send_json(200, {'ok': True, 'result': tool_get_profile_bindings({})})
            if command == 'quota': return self.send_json(200, read_antigravity_quota())
            if command == 'models': return self.send_json(200, model_status())
            from core.model_usage import usage_summary
            return self.send_json(200, usage_summary())
        if path == '/api/complete':
            prompt = str(body.get('prompt') or '')
            urgency = str(body.get('urgency') or 'daily')
            if not prompt or len(prompt) > 12000: return self.send_json(400, {'ok': False, 'code':'invalid_prompt'})
            if body.get('media'): return self.send_json(202, {'ok': True, 'handoff':'flow_tools', 'submitted':False})
            return self.send_json(200, complete(prompt, urgency=urgency, system=body.get('system')))
        return self.send_json(404, {'ok': False, 'code': 'not_found'})

if __name__ == '__main__':
    ThreadingHTTPServer(('127.0.0.1', 8767), Handler).serve_forever()
