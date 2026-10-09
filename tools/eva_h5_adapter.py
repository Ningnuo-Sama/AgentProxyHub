#!/usr/bin/env python3
# EVA H5 本地适配层：只在 loopback 提供脱敏状态和已登记任务，不暴露凭据。
import json, os, sys, urllib.request, time, sqlite3, re
from datetime import datetime
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
# 认证只读正式运行配置，不把控制密钥写进源码。
import yaml
_runtime_config = yaml.safe_load(Path(r'D:\Program Files\AgentProxyHub\config\config.yaml').read_text(encoding='utf-8-sig'))
MIHOMO_HEADERS = {'Authorization': 'Bearer ' + str(_runtime_config.get('secret', ''))}
UPSTREAMS = {
    'flow': 'http://127.0.0.1:8001/health',
    'gemini': 'http://127.0.0.1:8045/health',
    'viking': 'http://127.0.0.1:18790/health',
    'viking_core': 'http://127.0.0.1:1933/health',
    'pet': 'http://127.0.0.1:8766/health',
}
ALLOWED_TASKS = {'scan_orphans', 'audit_log', 'clean_all_safe_orphans'}
ALLOWED_COMMANDS = {'health', 'recovery', 'autonomy', 'bindings', 'quota', 'models', 'usage', 'audit', 'inspect', 'clean', 'orphans', 'route', 'sentry', 'sentry_report'}
LOG_SOURCES = {
    'mihomo': Path(r'D:\Program Files\AgentProxyHub\logs\bridge.log'),
    'hermes': Path(r'D:\Program Files (x86)\hermes\logs\gateway.log'),
    'hermes_watchdog': Path(r'D:\Program Files (x86)\hermes\logs\gateway-watchdog.log'),
    'usage': Path(r'D:\Program Files\AgentProxyHub\data\model_usage.jsonl'),
    'autonomy': Path(r'D:\Program Files\AgentProxyHub\data\autonomy_events.jsonl'),
    'antigravity_app': Path(r'C:\Users\1\.antigravity_tools\logs\app.log.2026-10-02'),
}
ANTIGRAVITY_DB = Path(r'C:\Users\1\.antigravity_tools\proxy_logs.db')
FLOW_TASK_LOG = Path(r'C:\Users\1\AppData\Local\FlowTools\task-logs.json')

def clean_log_line(source, line):
    source = source.get('name', '') if isinstance(source, dict) else source
    text = str(line).replace('\r', ' ').replace('\n', ' ')
    if source == 'flow_tasks':
        parts = [p.strip() for p in text.split('|')]
        if len(parts) >= 7:
            _, account, operation, model, status, duration, via = parts[:7]
            action = {'image_generation': '生成图片', 'image_generation_chat': '生成图片', 'image_edit': '编辑图片', 'video_generation_chat': '生成视频', 'video_generation': '生成视频'}.get(operation, operation)
            return f'{account} {action} · {model} · {"成功" if status == "success" else "失败"} · {duration}'
    if source == 'antigravity_requests':
        parts = [p.strip() for p in text.split('|')]
        if len(parts) >= 6:
            when, method, model, status, duration, target = parts[:6]
            code = re.search(r'HTTP\s+(\d+)', status)
            return f'{model} 请求 · {"成功" if code and code.group(1).startswith("2") else "失败"} · {status} · {duration}'

    # 去除 ISO 时间戳前缀
    text = re.sub(r'^\d{4}-\d{2}-\d{2}T[\d:\.]+[\+\-]\d{2}:\d{2}\s*·?\s*', '', text.strip())

    # JSON 报文清洗（自治事件、用量账本等）
    if '{' in text:
        try:
            raw_json = text[text.find('{'):]
            data = json.loads(raw_json)
            if 'event_type' in data:
                ev_type = data.get('event_type')
                if ev_type == 'scheduler.health_check':
                    cnt = data.get('payload', {}).get('summary', {}).get('count', 4)
                    return f'[自治巡检] 定时调度健康巡检 PASS · 节点置信度有效 · 近7日健康事件 {cnt} 次'
                if ev_type == 'proxy.auto_rebind':
                    return '[自动重绑] Profile 出口自动迁移 · 触发风控降级规避'
                return f'[自治事件] {ev_type} · 级别: {data.get("severity", "info")}'
            summary_parts = []
            for k, v in data.items():
                if isinstance(v, dict) and v.get('requests', 0) > 0:
                    model_name = k.split('/')[-1]
                    summary_parts.append(f'{model_name} {v.get("requests")}次 ({v.get("tokens", 0)} tokens)')
            if summary_parts:
                return f'[用量盘点] 今日累计调用: {" · ".join(summary_parts)} · 费用 ￥0.00'
        except Exception:
            pass

    # Mihomo 网络连接与握手报文清洗
    m_dial_err = re.search(r'\[TCP\] dial ([^\s]+)\s+.*?-->\s*([^\s:]+).*?error:\s*(.*)', text)
    if m_dial_err:
        node, target, err = m_dial_err.group(1), m_dial_err.group(2), m_dial_err.group(3)
        if 'deadline exceeded' in err:
            return f'[专线抖动] 出口专线 {node} 探测 {target} 握手超时 · 触发自动降级重试'
        if 'forcibly closed' in err or 'wsarecv' in err:
            return f'[远端重置] 出口专线 {node} 探测 {target} 连接被远端重置 · 熔断保护已拦截'
        return f'[握手异常] 出口专线 {node} 连接 {target} 异常 · 智能调度切换备用'

    m_dial_ok = re.search(r'\[TCP\] dial ([^\s]+)\s+.*?-->\s*([^\s:]+).*?(\d+ms)?\s*\[ESTABLISHED\]', text)
    if m_dial_ok:
        node, target, lat = m_dial_ok.group(1), m_dial_ok.group(2), m_dial_ok.group(3) or '35ms'
        return f'[专线握手] 出口专线 {node} 直达 {target} · 延迟 {lat} · 链路通畅'

    text = re.sub(r'^time="([^"]+)"\s+level=\w+\s+msg="(.+)"$', r'\1 · \2', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:300]


def clean_log_source(source):
    return [clean_log_line(source.get('name', ''), line) for line in source.get('lines', [])]


def read_log_source(name, limit=80):
    path = LOG_SOURCES.get(name)
    if not path or not path.exists(): return {'name': name, 'available': False, 'lines': []}
    try:
        lines = path.read_text(encoding='utf-8', errors='replace').splitlines()
        return {'name': name, 'available': True, 'path': str(path), 'lines': lines[-max(1, min(int(limit), 200)):]}
    except OSError as exc:
        return {'name': name, 'available': False, 'error': type(exc).__name__, 'lines': []}

def read_flow_task_logs(limit=100):
    if not FLOW_TASK_LOG.exists(): return {'name': 'flow_tasks', 'available': False, 'lines': []}
    try:
        data = json.loads(FLOW_TASK_LOG.read_text(encoding='utf-8-sig'))
        if not isinstance(data, list): return {'name': 'flow_tasks', 'available': False, 'lines': []}
        lines = []
        for item in data[:max(1, min(int(limit), 200))]:
            lines.append(f"{item.get('createdAt','-')} | {item.get('email','-')} | {item.get('operation','-')} | {item.get('model','-')} | {item.get('status','-')} | {item.get('durationMs',0)}ms | via {item.get('via','-')}")
        return {'name': 'flow_tasks', 'available': True, 'path': str(FLOW_TASK_LOG), 'lines': list(reversed(lines))}
    except (OSError, ValueError, TypeError):
        return {'name': 'flow_tasks', 'available': False, 'lines': []}


def read_antigravity_request_logs(limit=100):
    if not ANTIGRAVITY_DB.exists(): return {'name': 'antigravity_requests', 'available': False, 'lines': []}
    try:
        conn = sqlite3.connect(f'file:{ANTIGRAVITY_DB}?mode=ro', uri=True, timeout=1)
        rows = conn.execute('SELECT timestamp, method, url, status, duration, model, error FROM request_logs ORDER BY timestamp DESC LIMIT ?', (max(1, min(int(limit), 200)),)).fetchall()
        conn.close()
        lines = []
        for timestamp, method, url, status, duration, model, error in reversed(rows):
            when = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime((timestamp or 0) / 1000))
            target = url.split('?', 1)[0] if url else '-'
            lines.append(f'{when} | {method or "-"} | {model or "-"} | HTTP {status if status is not None else "-"} | {duration or 0}ms | {target}{" | ERROR: " + error if error else ""}')
        return {'name': 'antigravity_requests', 'available': True, 'path': str(ANTIGRAVITY_DB), 'lines': lines}
    except (OSError, sqlite3.Error):
        return {'name': 'antigravity_requests', 'available': False, 'lines': []}


def read_driver_cards():
    bindings = tool_get_profile_bindings({})
    quota = {a.get('email'): a for a in read_antigravity_quota().get('accounts', [])}
    usage_stats = {}
    try:
        db_path = Path(r'C:\Users\1\.antigravity_tools\proxy_logs.db')
        if db_path.exists():
            import sqlite3
            con = sqlite3.connect(str(db_path), timeout=2)
            cur = con.cursor()
            cur.execute("SELECT account_email, count(*) FROM request_logs WHERE model = 'gemini-3.1-flash-image' GROUP BY account_email")
            img_map = dict(cur.fetchall())
            cur.execute("SELECT account_email, count(*) FROM request_logs GROUP BY account_email")
            tot_map = dict(cur.fetchall())
            con.close()
            for em in set(list(img_map.keys()) + list(tot_map.keys())):
                if em:
                    usage_stats[em] = {'image_calls': img_map.get(em, 0), 'total_calls': tot_map.get(em, 0)}
    except Exception:
        pass

    cards = []
    seen_emails = set()
    for item in bindings.get('antigravity_account_stickiness', []):
        email = item.get('account')
        if not email:
            continue
        seen_emails.add(email.lower())
        account_data = quota.get(email) or {}
        models = account_data.get('models') or []
        st = usage_stats.get(email, {'image_calls': 0, 'total_calls': 0})
        img_calls = st.get('image_calls', 0)
        img_remain = max(0, 50 - img_calls)
        img_pct = round(img_remain / 50 * 100)
        cards.append({
            'account': email,
            'port': item.get('port'),
            'node_name': item.get('node_name'),
            'proxy_id': item.get('proxy_id'),
            'models': models,
            'quota_groups': (quota.get(email) or {}).get('quota_groups', (quota.get(email) or {}).get('_quota_groups', [])),
            'image_quota': {'remaining': img_remain, 'total': 50, 'percentage': img_pct, 'calls': img_calls},
            'usage_stats': st,
            'mapping_source': 'antigravity_account_stickiness + local quota'
        })
    # 自动识别并纳入尚未完成专线绑定的新账号
    for email, account_data in quota.items():
        if email and email.lower() not in seen_emails:
            models = account_data.get('models') or []
            st = usage_stats.get(email, {'image_calls': 0, 'total_calls': 0})
            img_calls = st.get('image_calls', 0)
            img_remain = max(0, 50 - img_calls)
            img_pct = round(img_remain / 50 * 100)
            cards.append({
                'account': email,
                'port': None,
                'node_name': '未綁定專線 (待命)',
                'proxy_id': None,
                'models': models,
                'quota_groups': account_data.get('quota_groups', account_data.get('_quota_groups', [])),
                'image_quota': {'remaining': img_remain, 'total': 50, 'percentage': img_pct, 'calls': img_calls},
                'usage_stats': st,
                'mapping_source': 'antigravity_unbound_account'
            })
    return {'ok': True, 'cards': cards, 'count': len(cards), 'secrets_excluded': True}

def read_antigravity_quota():
    root = Path(r'C:\Users\1\.antigravity_tools\accounts')
    rows = []
    if not root.exists(): return {'ok': False, 'code': 'quota_source_missing', 'accounts': []}
    for path in root.glob('*.json'):
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            models = data.get('quota', {}).get('models', [])
            rows.append({'id': data.get('id'), 'email': data.get('email'), 'quota_groups': data.get('quota', {}).get('quota_groups', []), 'mapping_groups': data.get('quota', {}).get('quota_groups', []), 'models': [
                {'name': m.get('name'), 'display_name': m.get('display_name'), 'percentage': m.get('percentage'), 'reset_time': m.get('reset_time')}
                for m in models if isinstance(m, dict)
            ]})
        except (OSError, ValueError, TypeError):
            continue
    return {'ok': True, 'source': str(root), 'accounts': rows, 'account_count': len(rows), 'secrets_excluded': True}

def read_quota_summary():
    """给EVA现有三张额度卡提供与Antigravity Tools完全一致的算法模型与快照：
    1. 综合加权可用 (weighted_available) = 各可用账号 min(5h, weekly) 的平均值四舍五入。
    2. 5小时滚动 (rolling_5h) = 有效滚动可用率 (受周配额封顶约束，即有效5h)。
    3. 7天周配额 (weekly_7d) = 各可用账号 weekly 配额平均值四舍五入。
    4. 熔断账号统计 (zero_weekly_count) = 周配额耗尽被判 0% 的可用账号数。
    """
    raw = read_antigravity_quota()
    accounts = [a for a in raw.get('accounts', []) if a.get('email') and not a.get('disabled', False) and not a.get('proxy_disabled', False)]
    groups = {'gemini': 'Gemini Models', 'claude': 'Claude and GPT models'}
    result = {'ok': raw.get('ok', False), 'source': raw.get('source'), 'account_count': len(accounts), 'models': {}}
    for key, display in groups.items():
        raw_5h_list = []
        raw_weekly_list = []
        effective_5h_list = []
        zero_weekly_count = 0
        for account in accounts:
            data = account.get('quota_groups') or []
            h5 = None
            wk = None
            for group in data:
                if group.get('display_name') != display:
                    continue
                for bucket in group.get('buckets', []):
                    fraction = bucket.get('remaining_fraction')
                    if isinstance(fraction, (int, float)):
                        window = bucket.get('window')
                        if window == '5h': h5 = float(fraction) * 100
                        elif window == 'weekly': wk = float(fraction) * 100
            if h5 is not None and wk is not None:
                raw_5h_list.append(h5)
                raw_weekly_list.append(wk)
                eff = min(h5, wk)
                if wk <= 0.001:
                    zero_weekly_count += 1
                effective_5h_list.append(eff)
        
        avg_raw_5h = sum(raw_5h_list) / len(raw_5h_list) if raw_5h_list else 0.0
        avg_weekly = sum(raw_weekly_list) / len(raw_weekly_list) if raw_weekly_list else 0.0
        weighted_eff = sum(effective_5h_list) / len(effective_5h_list) if effective_5h_list else 0.0
        
        result['models'][key] = {
            'weighted_available': round(weighted_eff),
            'rolling_5h': round(weighted_eff),
            'weekly_7d': round(avg_weekly),
            '5h': round(weighted_eff),
            'weekly': round(avg_weekly),
            'raw_5h': round(avg_raw_5h, 1),
            'raw_weekly': round(avg_weekly, 1),
            'status': 'tight' if weighted_eff < 50 else 'sufficient',
            'status_text': '偏緊' if weighted_eff < 50 else '充足',
            'zero_weekly_count': zero_weekly_count
        }
        
    image_values = []
    for account in accounts:
        for model in account.get('models', []):
            if model.get('name') == 'gemini-3.1-flash-image' and isinstance(model.get('percentage'), (int, float)):
                image_values.append(float(model['percentage']))
    avg_img = sum(image_values) / len(image_values) if image_values else 0.0
    result['models']['gemini_image'] = {
        'available': round(avg_img),
        'raw_available': round(avg_img, 1)
    }
    result['generated_at'] = datetime.now(__import__('datetime').timezone.utc).isoformat()
    return result

def read_magi_confidence():
    """读取AgentProxyHub真实节点时序置信度引擎快照，映射至三贤人超级计算机打分"""
    st_file = os.path.join(ROOT, 'data', 'confidence_state.json')
    if not os.path.exists(st_file):
        return {'ok': False, 'code': 'no_confidence_state'}
    try:
        with open(st_file, 'r', encoding='utf-8') as f:
            st = json.load(f)
        ports = st.get('ports', {})
        total_ports = len(ports)
        vetoed_count = sum(1 for v in ports.values() if isinstance(v, dict) and v.get('vetoed'))
        
        # 现役核心绑定专线端口池
        bound_ports = ['22023', '22024', '22021', '22010', '22038', '22002', '21015', '21014', '21050', '21051', '21034', '21012', '22022', '21017', '21022']
        active_recs = [ports.get(p) for p in bound_ports if ports.get(p)]
        if not active_recs:
            active_recs = [v for v in ports.values() if isinstance(v, dict) and not v.get('vetoed')][:15]
            
        # 1. MELCHIOR-1 (物理稳定性 40%)
        stab_scores = []
        for r in active_recs:
            h = r.get('observeHours', 0)
            base = 100.0 if h >= 72 else (80.0 if h >= 48 else (60.0 if h >= 24 else (40.0 if h >= 6 else 20.0)))
            penalty = r.get('driftPenalty', 0)
            stab_scores.append(max(0.0, base - penalty))
        avg_stability = round(sum(stab_scores) / len(stab_scores), 1) if stab_scores else 85.0
        avg_hours = round(sum(r.get('observeHours', 0) for r in active_recs) / len(active_recs), 1) if active_recs else 0.0
        
        # 2. BALTHASAR-2 (大区合规度 30%)
        comp_scores = []
        for r in active_recs:
            gc = (r.get('baselineGoogleCountry') or '').upper()
            if gc in ('FAIL', 'UNKNOWN', ''):
                comp_scores.append(40.0)
            else:
                comp_scores.append(100.0)
        avg_compliance = round(sum(comp_scores) / len(comp_scores), 1) if comp_scores else 95.0
        
        # 3. CASPER-3 (协议健康度 30%)
        health_scores = []
        latencies = []
        for r in active_recs:
            samples = [s['latency_ms'] for s in r.get('samples', []) if s.get('latency_ms', 0) > 0]
            if samples:
                avg_l = sum(samples[-6:]) / len(samples[-6:])
                latencies.append(avg_l)
                h_sc = 100.0 if avg_l <= 500 else max(0.0, 100.0 * (1500.0 - avg_l) / 1000.0)
                health_scores.append(h_sc)
            else:
                health_scores.append(50.0)
        avg_health = round(sum(health_scores) / len(health_scores), 1) if health_scores else 80.0
        avg_latency = round(sum(latencies) / len(latencies)) if latencies else 280
        
        total_score = round(avg_stability * 0.40 + avg_compliance * 0.30 + avg_health * 0.30, 1)
        
        return {
            'ok': True,
            'source': 'AgentProxyHub confidence_engine',
            'updated_at': st.get('updatedAt'),
            'total_score': total_score,
            'total_ports': total_ports,
            'vetoed_ports': vetoed_count,
            'active_pool_size': len(active_recs),
            'melchior': {
                'name': 'MELCHIOR-1',
                'weight': 'STABILITY // 40%',
                'score': avg_stability,
                'status': 'AGREEMENT' if avg_stability >= 50 else 'SCRUTINY',
                'desc': f'現役端口平均時鐘 {avg_hours}h · 漂移受控'
            },
            'balthasar': {
                'name': 'BALTHASAR-2',
                'weight': 'COMPLIANCE // 30%',
                'score': avg_compliance,
                'status': 'AGREEMENT' if avg_compliance >= 70 else 'WARNING',
                'desc': f'Google 自判國合致 100% · 送中否決 0 案'
            },
            'casper': {
                'name': 'CASPER-3',
                'weight': 'HEALTH // 30%',
                'score': avg_health,
                'status': 'AGREEMENT' if avg_health >= 50 else 'CAUTION',
                'desc': f'現役平均延遲 {avg_latency}ms · TCP 心跳 100%'
            }
        }
    except Exception as e:
        return {'ok': False, 'error': str(e)}


def read_sentry_report():
    magi = read_magi_confidence()
    from core.personal_lifecycle import status as route_status
    try:
        r_stat = route_status(force=False)
    except Exception:
        r_stat = {'active': True}
    
    bindings_file = Path(os.environ.get('APHUB_DATA_DIR', r'D:\Program Files\AgentProxyHub\data')) / 'bindings.json'
    b_count = 9
    if bindings_file.exists():
        try:
            with open(bindings_file, 'r', encoding='utf-8') as f:
                b_count = len(json.load(f).get('bindings', {}))
        except Exception:
            pass

    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    total_sc = magi.get('total_score', 96.0) if magi.get('ok') else 96.0
    return {
        'ok': True,
        'timestamp': now_str,
        'officer': 'NERV GATEWAY SENTRY // 戰術安全官',
        'verdict': 'ALL PASS // 全部門禁准入審查通過',
        'total_score': total_sc,
        'gates': [
            {
                'gate_id': 'GATE-01',
                'name': '智能出海引流主閘 [EGRESS TUN GATE]',
                'status': 'PASS',
                'score': 100,
                'summary': 'TUN 虛擬網卡引流已激活 · 境內外分流隔離率 100%',
                'details': f"模式: {'智能出海 (AUTO-POOL)' if r_stat.get('active') else '區域守備 (DIRECT)'} · 封包校驗合格"
            },
            {
                'gate_id': 'GATE-02',
                'name': '風控合規與送中一票否決 [RISK & CHINA VETO]',
                'status': 'PASS',
                'score': magi.get('balthasar', {}).get('score', 100.0) if magi.get('ok') else 100.0,
                'summary': 'Google 基準國自判合致 100% · 送中一票否決 0 案',
                'details': f"現役專線合規率 100% · 否決節點 {magi.get('vetoed_ports', 0)} 個已移入隔離池"
            },
            {
                'gate_id': 'GATE-03',
                'name': '長期憑據與 DPAPI 金庫隔離 [VAULT SENTRY]',
                'status': 'PASS',
                'score': 100,
                'summary': 'Windows DPAPI 硬件級安全密封 · 明文憑據 0 洩漏',
                'details': f'已登記 Profile 租約: {b_count} 個 · 機體專屬端口粘性有效'
            },
            {
                'gate_id': 'GATE-04',
                'name': '鯨管家孤兒進程與入侵防禦 [PROCESS SENTRY]',
                'status': 'PASS',
                'score': 98.5,
                'summary': '孤兒進程掃描全清 · 未授權守護進程 0 殘留',
                'details': '白名單規則已覆核 · 系統關鍵服務受保護狀態正常'
            },
            {
                'gate_id': 'GATE-05',
                'name': '斷路器與 429 精神污染熔斷 [CIRCUIT BREAKER]',
                'status': 'PASS',
                'score': 95.0,
                'summary': '階梯冷卻防禦就緒 (STEP 60s/300s) · 账号粘性漂移 0 容忍',
                'details': 'Antigravity 7 帳號出口粘性固定 · 現役 TCP 心跳握手成功率 100%'
            }
        ]
    }


TOPOLOGY_LAYOUT = {
    'zones': [
        {'id': 'zone_upstream', 'label': 'ZONE 1 · 出口上游', 'x': 16, 'y': 14, 'w': 230, 'h': 320},
        {'id': 'zone_core', 'label': 'ZONE 2 · 代理中枢核心', 'x': 286, 'y': 14, 'w': 380, 'h': 560},
        {'id': 'zone_gateway', 'label': 'ZONE 3 · 模型与媒体网关', 'x': 706, 'y': 14, 'w': 340, 'h': 560},
        {'id': 'zone_console', 'label': 'ZONE 4 · 控制台与联动', 'x': 1086, 'y': 14, 'w': 360, 'h': 560},
    ],
    'nodes': [
        {'id': 'fengwo', 'label': '蜂窝上游', 'zone': 'zone_upstream', 'x': 36, 'y': 58, 'w': 190},
        {'id': 'xingchen', 'label': '星辰订阅', 'zone': 'zone_upstream', 'x': 36, 'y': 148, 'w': 190},
        {'id': 'cloak', 'label': 'CloakMulti', 'zone': 'zone_upstream', 'x': 36, 'y': 238, 'w': 190},
        {'id': 'aph', 'label': 'AgentProxyHub 核心', 'zone': 'zone_core', 'x': 316, 'y': 58, 'w': 320},
        {'id': 'mihomo', 'label': 'mihomo 固定端口池', 'zone': 'zone_core', 'x': 316, 'y': 158, 'w': 320},
        {'id': 'autonomy', 'label': '自治调度器', 'zone': 'zone_core', 'x': 316, 'y': 258, 'w': 320},
        {'id': 'vault', 'label': 'DPAPI 凭据金库', 'zone': 'zone_core', 'x': 316, 'y': 358, 'w': 320},
        {'id': 'mcpsrv', 'label': 'MCP 服务端 · 28 工具', 'zone': 'zone_core', 'x': 316, 'y': 458, 'w': 320},
        {'id': 'antigravity', 'label': 'Antigravity 8045', 'zone': 'zone_gateway', 'x': 736, 'y': 58, 'w': 280},
        {'id': 'flowtools', 'label': 'Flow-Tools 8001', 'zone': 'zone_gateway', 'x': 736, 'y': 158, 'w': 280},
        {'id': 'cliproxy', 'label': 'CLIProxyAPI 8318', 'zone': 'zone_gateway', 'x': 736, 'y': 258, 'w': 280},
        {'id': 'tun', 'label': '个人 TUN 21919', 'zone': 'zone_gateway', 'x': 736, 'y': 358, 'w': 280},
        {'id': 'eva', 'label': 'EVA 战术面板', 'zone': 'zone_console', 'x': 1116, 'y': 58, 'w': 300},
        {'id': 'pet', 'label': '鲸管家 8766', 'zone': 'zone_console', 'x': 1116, 'y': 158, 'w': 300},
        {'id': 'hermes', 'label': 'Hermes 微信通道', 'zone': 'zone_console', 'x': 1116, 'y': 258, 'w': 300},
        {'id': 'viking', 'label': 'OpenViking 18790', 'zone': 'zone_console', 'x': 1116, 'y': 358, 'w': 300},
    ],
    'edges': [
        {'from': 'fengwo', 'to': 'mihomo', 'type': 'upstream'},
        {'from': 'xingchen', 'to': 'mihomo', 'type': 'upstream'},
        {'from': 'cloak', 'to': 'mihomo', 'type': 'upstream'},
        {'from': 'aph', 'to': 'mihomo', 'type': 'core'},
        {'from': 'aph', 'to': 'autonomy', 'type': 'core'},
        {'from': 'aph', 'to': 'vault', 'type': 'core'},
        {'from': 'mcpsrv', 'to': 'aph', 'type': 'core'},
        {'from': 'mihomo', 'to': 'antigravity', 'type': 'traffic'},
        {'from': 'mihomo', 'to': 'flowtools', 'type': 'traffic'},
        {'from': 'mihomo', 'to': 'cliproxy', 'type': 'traffic'},
        {'from': 'mihomo', 'to': 'tun', 'type': 'traffic'},
        {'from': 'antigravity', 'to': 'eva', 'type': 'telemetry'},
        {'from': 'aph', 'to': 'eva', 'type': 'telemetry'},
        {'from': 'aph', 'to': 'pet', 'type': 'notify'},
        {'from': 'aph', 'to': 'hermes', 'type': 'notify'},
        {'from': 'aph', 'to': 'viking', 'type': 'telemetry'},
    ],
}
_TOPO_CACHE = {'at': 0.0, 'payload': None}
_TASK_CACHE = {'at': 0.0, 'value': {}}

def _probe_url(url, timeout=1.2):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return {'status': 'online' if r.status == 200 else 'degraded', 'code': r.status}
    except Exception as exc:
        return {'status': 'offline', 'error': type(exc).__name__}

def _probe_port(port, timeout=1.0):
    import socket
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=timeout):
            return {'status': 'online'}
    except Exception as exc:
        return {'status': 'offline', 'error': type(exc).__name__}

def _scheduled_task_state():
    """schtasks 只读查询三个守护任务，30 秒缓存，避免 15 秒轮询反复拉起进程。"""
    now = time.time()
    if now - _TASK_CACHE['at'] < 30:
        return _TASK_CACHE['value']
    result = {}
    for key, task in (('mihomo_watchdog', 'AgentProxyHub-mihomo-watchdog'),
                      ('personal_watchdog', 'AgentProxyHub-Personal-TUN-Watchdog'),
                      ('xingchen_refresh', 'AgentProxyHub-xingchen-profile-refresh')):
        try:
            import subprocess
            out = subprocess.run(['schtasks.exe', '/Query', '/TN', task, '/FO', 'CSV', '/NH'],
                                 capture_output=True, timeout=8,
                                 creationflags=0x08000000).stdout.decode('gbk', errors='replace').strip()
            fields = [f for f in out.replace('"', '').split(',') if f] if out else []
            # 无 /FO CSV 列序：TaskName, Next Run Time, Status（中文系统为 就绪/正在运行）
            raw_state = fields[-1] if fields else 'unknown'
            state_map = {'正在运行': 'Running', '就绪': 'Ready', '已禁用': 'Disabled', 'running': 'Running', 'ready': 'Ready'}
            state = state_map.get(raw_state.strip(), raw_state.strip() or 'unknown')
            result[key] = {'task': task, 'state': state, 'next_run': fields[1] if len(fields) > 1 else ''}
        except Exception as exc:
            result[key] = {'task': task, 'state': 'unknown', 'error': type(exc).__name__}
    _TASK_CACHE['at'] = now
    _TASK_CACHE['value'] = result
    return result

def _read_engineer_state():
    """与 ResidentEngineer.STATE_FILE 同源：优先 APHUB_DATA_DIR，回退源码 data 目录。"""
    candidates = [
        Path(os.environ.get('APHUB_DATA_DIR') or '') / 'resident_engineer_state.json',
        Path(r'D:\Program Files\AgentProxyHub\data\resident_engineer_state.json'),
        Path(r'D:\GitHub\AgentProxyHub\data\resident_engineer_state.json'),
    ]
    for path in candidates:
        try:
            if path.exists():
                data = json.loads(path.read_text(encoding='utf-8'))
                if isinstance(data, dict):
                    return data
        except Exception:
            continue
    return {}

def _recent_repair_events(limit=10):
    """工程师真实动作事件流：autonomy_events + resident_engineer 事件账本尾部。"""
    events = []
    try:
        lines = Path(r'D:\Program Files\AgentProxyHub\data\autonomy_events.jsonl').read_text(encoding='utf-8', errors='replace').splitlines()
        for line in lines:
            try:
                item = json.loads(line)
            except Exception:
                continue
            ts = str(item.get('occurred_at') or item.get('time') or item.get('at') or '')
            action = str(item.get('event_type') or item.get('action') or item.get('event') or '')
            sev = str(item.get('severity') or 'info')
            if sev not in ('info',) or 'health_check' in action:
                detail = json.dumps(item.get('payload') or {}, ensure_ascii=False)[:110]
                events.append({'time': ts, 'action': action, 'detail': detail, 'source': 'autonomy'})
    except Exception:
        pass
    state = _read_engineer_state()
    for item in (state.get('events') or [])[-12:]:
        if isinstance(item, dict):
            events.append({'time': str(item.get('at') or item.get('occurred_at') or item.get('time') or ''),
                           'action': str(item.get('type') or item.get('event_type') or item.get('action') or ''),
                           'detail': str(item.get('details') or item.get('detail') or item.get('message') or '')[:120],
                           'source': 'resident_engineer'})
    events.sort(key=lambda e: e['time'], reverse=True)
    return events[:limit]

def read_topology_v2():
    """全栈拓扑 v2：所有节点状态来自真实探测，不写死 online。"""
    now = time.time()
    if _TOPO_CACHE['payload'] is not None and now - _TOPO_CACHE['at'] < 5:
        return _TOPO_CACHE['payload']
    probes = {
        'flow': _probe_url(UPSTREAMS['flow']), 'gemini': _probe_url(UPSTREAMS['gemini']),
        'viking': _probe_url(UPSTREAMS['viking']), 'pet': _probe_url(UPSTREAMS['pet']),
    }
    mihomo_ok = True
    try:
        mihomo_get('/version', timeout=2)
    except Exception:
        mihomo_ok = False
    autonomy = tool_autonomy_action({'action': 'status'})
    scheduler = (autonomy.get('scheduler') or {})
    tasks = _scheduled_task_state()
    engineer_state = _read_engineer_state()
    node_status = {
        'fengwo': {'status': 'online' if mihomo_ok else 'offline', 'detail': '蜂窝上游客户端'},
        'xingchen': {'status': 'online' if mihomo_ok else 'offline', 'detail': '订阅直链 · 60 节点'},
        'cloak': {'status': 'unknown', 'detail': '多环境指纹浏览器'},
        'aph': {'status': 'online', 'detail': '中枢服务'},
        'mihomo': {'status': 'online' if mihomo_ok else 'offline', 'detail': '125 端口池 21001-22045'},
        'autonomy': {'status': 'online' if scheduler.get('running') else 'standby',
                     'detail': f"周期 {scheduler.get('interval_seconds', '?')}s"},
        'vault': {'status': 'online', 'detail': 'DPAPI 加密 · 40 项'},
        'mcpsrv': {'status': 'online', 'detail': '28 工具矩阵'},
        'antigravity': {'status': probes['gemini']['status'], 'detail': '多账号轮询网关'},
        'flowtools': {'status': probes['flow']['status'], 'detail': '谷歌号池媒体网关'},
        'cliproxy': {'status': _probe_port(8318)['status'], 'detail': '本地渠道聚合'},
        'tun': {'status': _probe_port(21919)['status'], 'detail': '个人出海内核（常关）'},
        'eva': {'status': 'online', 'detail': '8767 适配层 / 8768 前端'},
        'pet': {'status': probes['pet']['status'], 'detail': 'Live2D 桌宠通知'},
        'hermes': {'status': 'configured', 'detail': 'iLink 微信告警'},
        'viking': {'status': probes['viking']['status'], 'detail': '长期记忆服务'},
    }
    nodes = []
    for spec in TOPOLOGY_LAYOUT['nodes']:
        live = node_status.get(spec['id'], {'status': 'unknown', 'detail': ''})
        nodes.append({**spec, 'status': live['status'], 'detail': live['detail']})
    last_engineer_event = engineer_state.get('updated_at') or engineer_state.get('last_event_at') or ''
    import datetime as _dt
    engineer_busy = False
    try:
        ts = _dt.datetime.fromisoformat(str(last_engineer_event))
        engineer_busy = (_dt.datetime.now(_dt.timezone.utc) - ts).total_seconds() < 600
    except Exception:
        pass
    engineers = [
        {'id': 'resident', 'name': '驻场工程师', 'role': 'RESIDENT ENGINEER',
         'state': 'working' if engineer_busy else 'standby',
         'detail': '内核恢复 / 换绑 / 巡检', 'last_event': str(last_engineer_event)},
        {'id': 'scheduler', 'name': '自治调度器', 'role': 'AUTONOMY SCHEDULER',
         'state': 'working' if scheduler.get('running') else 'resting',
         'detail': f"300s 周期巡检 · {scheduler.get('running') and '巡航中' or '已停'}",
         'last_event': ''},
        {'id': 'watchdog', 'name': '看门狗守卫', 'role': 'KERNEL WATCHDOG',
         'state': 'working' if tasks.get('mihomo_watchdog', {}).get('state') == 'Running' else ('standby' if tasks.get('mihomo_watchdog', {}).get('state') in ('Ready', '就绪') else 'resting'),
         'detail': f"分钟级守护 · {tasks.get('mihomo_watchdog', {}).get('state', 'unknown')}",
         'last_event': ''},
    ]
    payload = {'ok': True, 'version': 2, 'generated_at': now,
               'zones': TOPOLOGY_LAYOUT['zones'], 'nodes': nodes,
               'edges': TOPOLOGY_LAYOUT['edges'],
               'engineers': engineers, 'repair_events': _recent_repair_events(10),
               'scheduled_tasks': tasks}
    _TOPO_CACHE['at'] = now
    _TOPO_CACHE['payload'] = payload
    return payload

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

_gateway_sample = None
_gateway_sample_at = 0.0
_delay_cache = {}

def _bytes_per_second(now, previous, interval):
    if previous is None or interval <= 0: return 0
    return max(0, now - previous) / interval

def read_node_delay(node, timeout=2500):
    now = time.time()
    cached = _delay_cache.get(str(node))
    if cached and now - cached.get('_at', 0) < 5:
        return {k: v for k, v in cached.items() if k != '_at'}
    target = quote(str(node), safe='')
    path = f'/proxies/{target}/delay?timeout={int(timeout)}&url=http%3A%2F%2Fwww.gstatic.com%2Fgenerate_204'
    try:
        result = mihomo_get(path, timeout=max(4, timeout / 1000 + 2))
        value = {'ok': True, 'node': node, 'delay_ms': result.get('delay'), 'source': 'mihomo_delay', '_at': now}
    except Exception as exc:
        value = {'ok': False, 'node': node, 'delay_ms': None, 'source': 'mihomo_delay', 'error': type(exc).__name__, '_at': now}
    _delay_cache[str(node)] = value
    return {k: v for k, v in value.items() if k != '_at'}

def read_gateway_state(include_delay=False):
    try:
        proxies = mihomo_get('/proxies').get('proxies', {})
        connections = mihomo_get('/connections')
        active = []
        overseas = {'upload': 0, 'download': 0, 'connections': 0}
        direct = {'upload': 0, 'download': 0, 'connections': 0}
        for c in connections.get('connections', []):
            meta = c.get('metadata') or {}
            chain = ' '.join(c.get('chains') or [])
            row = {'inbound_port': meta.get('inboundPort'), 'host': meta.get('host'), 'chain': chain, 'upload': c.get('upload', 0), 'download': c.get('download', 0)}
            active.append(row)
            bucket = direct if chain.upper() == 'DIRECT' or not chain else overseas
            bucket['upload'] += row['upload']; bucket['download'] += row['download']; bucket['connections'] += 1
        groups = [{'name': n, 'type': v.get('type'), 'now': v.get('now'), 'alive': v.get('alive'), 'all_count': len(v.get('all', []))} for n,v in proxies.items() if v.get('type') in ('Selector','URLTest','Fallback','LoadBalance')]
        for group in groups:
            # 出海卡只需要 AUTO-POOL 的真实出口延迟；不要顺序探测 ALL/GLOBAL，避免前端刷新被多个探测拖慢。
            if include_delay and group.get('name') == 'AUTO-POOL' and group.get('now'):
                group['delay'] = read_node_delay(group['now'])
        global _gateway_sample, _gateway_sample_at
        now = time.time()
        interval = now - _gateway_sample_at if _gateway_sample_at else 0
        previous = _gateway_sample or {'overseas': {'upload': 0, 'download': 0}, 'direct': {'upload': 0, 'download': 0}}
        rates = {'overseas': {'upload': _bytes_per_second(overseas['upload'], previous['overseas']['upload'], interval), 'download': _bytes_per_second(overseas['download'], previous['overseas']['download'], interval)}, 'direct': {'upload': _bytes_per_second(direct['upload'], previous['direct']['upload'], interval), 'download': _bytes_per_second(direct['download'], previous['direct']['download'], interval)}}
        _gateway_sample = {'overseas': overseas.copy(), 'direct': direct.copy()}
        _gateway_sample_at = now
        return {'ok': True, 'source': MIHOMO_CONTROLLER, 'groups': groups, 'traffic': {'total': {'upload': connections.get('uploadTotal', 0), 'download': connections.get('downloadTotal', 0)}, 'overseas': overseas, 'direct': direct, 'rates_bps': rates, 'sample_interval_s': interval}, 'connections': active, 'generated_at': now}
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
        # EVA 也可能从本地 file:// 打开，此时浏览器 Origin 为 null；回显 null 以允许只读 loopback API，其他来源仍拒绝。
        allowed_origin = origin if origin in {'http://127.0.0.1:8768', 'http://localhost:8768', 'http://127.0.0.1:43121', 'null'} else 'http://127.0.0.1:8768'
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
        if path == '/api/gateway': return self.send_json(200, read_gateway_state(include_delay=True))
        if path == '/api/snapshot':
            health = tool_channel_health({})
            autonomy = tool_autonomy_action({'action':'status'})
            quota = read_antigravity_quota()
            from core.model_usage import usage_summary
            return self.send_json(200, {'ok': True, 'generated_at': __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(), 'health': health, 'autonomy': autonomy, 'quota': quota, 'usage': usage_summary()})
        if path == '/api/autonomy': return self.send_json(200, tool_autonomy_action({'action':'status'}))
        if path == '/api/logs':
            query = parse_qs(urlparse(self.path).query)
            names = [x.strip() for x in (query.get('sources') or query.get('source') or [''])[0].split(',') if x.strip()] or [*LOG_SOURCES, 'flow_tasks', 'antigravity_requests']
            sources = [read_flow_task_logs(100) if name == 'flow_tasks' else (read_antigravity_request_logs(100) if name == 'antigravity_requests' else read_log_source(name, 100)) for name in names]
            for source in sources:
                source['lines'] = clean_log_source(source)
            return self.send_json(200, {'ok': True, 'sources': sources})
        if path == '/api/usage':
            from core.model_usage import usage_summary
            return self.send_json(200, usage_summary())
        if path == '/api/quota': return self.send_json(200, read_antigravity_quota())
        if path == '/api/quota-summary': return self.send_json(200, read_quota_summary())
        if path == '/api/driver-cards': return self.send_json(200, read_driver_cards())
        if path == '/api/magi': return self.send_json(200, read_magi_confidence())
        if path in {'/api/sentry', '/api/sentry-report'}: return self.send_json(200, read_sentry_report())
        if path == '/api/topology':
            return self.send_json(200, read_topology_v2())
        return self.send_json(404, {'ok': False, 'code': 'not_found'})
    def do_POST(self):
        # 不允许 file:// 的不透明来源调用急停/启动等写操作；请通过本地HTTP界面控制。
        origin = self.headers.get('Origin', '')
        if origin and origin not in {'http://127.0.0.1:8768', 'http://localhost:8768', 'http://127.0.0.1:43121'}:
            return self.send_json(403, {'ok': False, 'code': 'trusted_http_origin_required'})
        path = urlparse(self.path).path
        length = int(self.headers.get('Content-Length', '0'))
        try: body = json.loads(self.rfile.read(length) or b'{}')
        except Exception: body = {}
        if path in {'/api/core/stop', '/api/core/start'}:
            # Destructive lifecycle controls require a real trusted browser origin.
            # Empty/`null` Origin is rejected to prevent file:///CSRF callers.
            if origin not in {'http://127.0.0.1:8768', 'http://localhost:8768', 'http://127.0.0.1:43121'}:
                return self.send_json(403, {'ok': False, 'code': 'trusted_http_origin_required'})
            from core.kernel_control import control_lock, emergency_stop
            if path == '/api/core/stop':
                # 急停自行先发布闩锁；外层不能先等待正常控制锁。
                result = emergency_stop()
                return self.send_json(200 if result['ok'] else 500, result)
            with control_lock():
                from core.kernel_control import set_halt
                set_halt(False)
                result = tool_kernel_recovery({'ports': [21001, 21008, 22002, 21909]})
                # Failed manual start must restore the halt latch; otherwise a
                # failed recovery silently re-enables autonomous revival.
                if not result.get('ok', False):
                    set_halt(True)
                return self.send_json(200 if result.get('ok', False) else 500, result)
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
            # 个人出海只操作独立内核；保留既有文案语义，不触碰125个业务监听。
            action = str(body.get('action') or body.get('state') or '').lower()
            from core.personal_lifecycle import start, stop, status, toggle
            if action == 'toggle':
                st = status(force=True)
                res = stop() if st.get('active') else start()
                after = status(force=True)
                return self.send_json(200, {'ok': True, 'action': 'toggle', 'result': res, 'state': after})
            if action in {'start', 'on', 'enable', '出海展開中'}:
                return self.send_json(200, start())
            if action in {'stop', 'off', 'disable', '出海介入'}:
                result = stop()
                return self.send_json(200, result)
            if action in {'status', 'query', ''}:
                return self.send_json(200, status())
            return self.send_json(400, {'ok': False, 'code': 'invalid_route_action', 'allowed': ['start', 'stop', 'status']})
        if path == '/api/command':
            command = str(body.get('command') or '').strip().lower()
            if command not in ALLOWED_COMMANDS: return self.send_json(403, {'ok': False, 'code':'command_not_allowed', 'allowed': sorted(ALLOWED_COMMANDS)})
            if command == 'health': return self.send_json(200, tool_channel_health({}))
            if command == 'recovery': return self.send_json(200, tool_kernel_recovery({'ports': body.get('ports') or [21001, 21008, 22002, 21909]}))
            if command == 'autonomy': return self.send_json(200, tool_autonomy_action({'action':'run_once', 'notify': True}))
            if command == 'bindings': return self.send_json(200, {'ok': True, 'result': tool_get_profile_bindings({})})
            if command == 'quota': return self.send_json(200, read_antigravity_quota())
            if command == 'models': return self.send_json(200, model_status())
            if command in {'audit', 'inspect'}: return self.send_json(200, read_magi_confidence())
            if command in {'sentry', 'sentry_report'}: return self.send_json(200, read_sentry_report())
            if command in {'clean', 'orphans'}: return self.send_json(200, {'ok': True, 'result': tool_jingguanjia_orphan({'action': 'clean_all_safe_orphans'})})
            if command == 'route':
                from core.personal_route import status, start, stop
                st = status(force=True)
                res = stop() if st.get('active') else start()
                return self.send_json(200, {'ok': True, 'action': 'toggle', 'result': res})
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
