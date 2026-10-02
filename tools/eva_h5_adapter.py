#!/usr/bin/env python3
# EVA H5 本地适配层：只在 loopback 提供脱敏状态和已登记任务，不暴露凭据。
import json, os, sys, urllib.request
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault('APHUB_DATA_DIR', r'D:\Program Files\AgentProxyHub\data')
from mcp.server import tool_jingguanjia_orphan, tool_get_profile_bindings, tool_autonomy_action, tool_channel_health
from core.model_router import complete, status as model_status
from core.alert_dispatch import notify_all

UPSTREAMS = {
    'flow': 'http://127.0.0.1:8001/health',
    'gemini': 'http://127.0.0.1:8045/health',
    'viking': 'http://127.0.0.1:18790/health',
    'pet': 'http://127.0.0.1:8766/health',
}
ALLOWED_TASKS = {'scan_orphans', 'audit_log', 'clean_all_safe_orphans'}
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
        if path == '/api/autonomy': return self.send_json(200, tool_autonomy_action({'action':'status'}))
        if path == '/api/logs':
            names = [x.strip() for x in str(urlparse(self.path).query.replace('sources=', '')).split(',') if x.strip()] or list(LOG_SOURCES)
            return self.send_json(200, {'ok': True, 'sources': [read_log_source(name, 100) for name in names]})
        if path == '/api/usage':
            from core.model_usage import usage_summary
            return self.send_json(200, usage_summary())
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
        if path == '/api/complete':
            prompt = str(body.get('prompt') or '')
            urgency = str(body.get('urgency') or 'daily')
            if not prompt or len(prompt) > 12000: return self.send_json(400, {'ok': False, 'code':'invalid_prompt'})
            if body.get('media'): return self.send_json(202, {'ok': True, 'handoff':'flow_tools', 'submitted':False})
            return self.send_json(200, complete(prompt, urgency=urgency, system=body.get('system')))
        return self.send_json(404, {'ok': False, 'code': 'not_found'})

if __name__ == '__main__':
    ThreadingHTTPServer(('127.0.0.1', 8767), Handler).serve_forever()
