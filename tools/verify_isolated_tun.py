"""有界双内核演练；不重启业务、不调用生成API，finally仅退出个人。"""
import ipaddress
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid
import yaml
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.business_route_exclusions import endpoint_hosts, dns_endpoint_hosts, apply_exclusions
from core.personal_tun_isolation import build_isolated_candidate
from core.kernel_control import control_lock, is_halted, PERSONAL_EXE, stop_personal_kernel
from core.tun_controller import TunController


def ps(script):
    p = subprocess.run(['powershell.exe', '-NoProfile', '-Command', script],
                       capture_output=True, text=True, timeout=8)
    if p.returncode:
        raise RuntimeError('powershell_probe_failed')
    return json.loads(p.stdout) if p.stdout.strip() else None


def probe(remote=False):
    args = ['curl.exe', '--noproxy', '', '--connect-timeout', '4', '--max-time', '8',
            '-sS', '-o', 'NUL', '-w', '%{http_code}']
    if remote:
        args += ['--socks5-hostname', '127.0.0.1:21012']
    p = subprocess.run(args + ['https://www.google.com/generate_204'], capture_output=True,
                       text=True, timeout=10)
    return {'ok': p.returncode == 0 and p.stdout == '204', 'exit': p.returncode,
            'http': p.stdout, 'error': p.stderr.strip()[:120]}


def business_identity():
    value = ps("@(Get-CimInstance Win32_Process -Filter \"Name='mihomo.exe'\" | Where-Object ExecutablePath -eq 'D:\\Program Files\\AgentProxyHub\\bin\\mihomo.exe' | Select-Object ProcessId,CreationDate) | ConvertTo-Json -Compress")
    return value if isinstance(value, list) else ([value] if value else [])


def connections(pid):
    value = ps(f"@(Get-NetTCPConnection -OwningProcess {pid} -State Established -ErrorAction SilentlyContinue | Select-Object LocalAddress,LocalPort,RemoteAddress,RemotePort,CreationTime) | ConvertTo-Json -Compress")
    rows = value if isinstance(value, list) else ([value] if value else [])
    return {tuple(str(row.get(key)) for key in ('LocalAddress','LocalPort','RemoteAddress','RemotePort','CreationTime')) for row in rows}


def main():
    if is_halted() or TunController().status().get('tun_enabled') is not False:
        raise RuntimeError('unsafe_baseline')
    before = business_identity()
    if not isinstance(before, list) or len(before) != 1:
        raise RuntimeError('single_business_instance_required')
    pid = before[0]['ProcessId']
    b = yaml.safe_load(Path(r'D:\Program Files\AgentProxyHub\config\config.yaml').read_text(encoding='utf-8-sig'))
    resolved = {}
    for host in sorted(set(endpoint_hosts(b)) | set(dns_endpoint_hosts(b))):
        try:
            ipaddress.ip_address(host)
            continue
        except ValueError:
            pass
        result = ps("@(Resolve-DnsName -Name '" + host.replace("'", "''") + "' -Type A -DnsOnly -QuickTimeout -ErrorAction Stop | Where-Object IPAddress | Select-Object -ExpandProperty IPAddress) | ConvertTo-Json -Compress")
        resolved[host] = result if isinstance(result, list) else [result]
    active = ps(f"@(Get-NetTCPConnection -OwningProcess {pid} -State Established -ErrorAction SilentlyContinue | Select-Object -ExpandProperty RemoteAddress -Unique) | ConvertTo-Json -Compress") or []
    c, evidence = apply_exclusions(build_isolated_candidate(b), b, resolved, active_addresses=active)
    c['tun']['enable'] = True
    config = Path(r'D:\Program Files\AgentProxyHub\personal') / ('test-active-' + uuid.uuid4().hex + '.yaml')
    if config.exists():
        raise RuntimeError('existing_test_config_requires_review')
    config.write_text(yaml.safe_dump(c,allow_unicode=True,sort_keys=False), encoding='utf-8')
    result = {'exclusions': evidence, 'business_before': before, 'baseline_socks': probe(True)}
    if not result['baseline_socks']['ok']:
        print(json.dumps(result)); return 2
    checked = subprocess.run([PERSONAL_EXE, '-t', '-d', str(config.parent), '-f', str(config)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
    if checked.returncode:
        raise RuntimeError('candidate_invalid')
    existing_connections = connections(pid)
    result['existing_connections_before'] = len(existing_connections)
    try:
        with control_lock():
            if is_halted(): raise RuntimeError('manual_halt')
            instances = ps("@(Get-CimInstance Win32_Process -Filter \"Name='mihomo.exe'\" | Where-Object ExecutablePath -eq 'D:\\Program Files\\AgentProxyHub\\personal\\mihomo.exe').Count | ConvertTo-Json")
            if instances: raise RuntimeError('personal_already_running')
            subprocess.Popen([PERSONAL_EXE, '-d', str(config.parent), '-f', str(config)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(3)
        result['personal'] = TunController(config).status()
        result['socks_during'] = probe(True)
        result['system_during'] = probe()
        result['existing_connections_retained_during'] = len(existing_connections & connections(pid))
        addresses = sorted({v for values in resolved.values() for v in values} | {a for a in active if not ipaddress.ip_address(a).is_loopback} | {'223.5.5.5'})
        routes = []
        for address in addresses:
            rows = ps("@(Find-NetRoute -RemoteIPAddress '" + address + "' | Select-Object InterfaceAlias,DestinationPrefix) | ConvertTo-Json -Compress")
            routes.append({'address':address,'routes':rows})
        result['endpoint_routes'] = routes
    finally:
        result['stop'] = stop_personal_kernel()
        time.sleep(2)
        result['business_after'] = business_identity()
        result['business_unchanged'] = result['business_after'] == before
        result['personal_adapters_after'] = ps("@(Get-NetAdapter | Where-Object Name -eq 'APH-Personal').Count | ConvertTo-Json")
        result['personal_routes_after'] = ps("@(Get-NetRoute | Where-Object InterfaceAlias -eq 'APH-Personal').Count | ConvertTo-Json")
        result['existing_connections_retained_after'] = len(existing_connections & connections(pid))
    physical = b['interface-name']
    result['endpoint_routes_physical'] = all(
        item['routes'] and all(row.get('InterfaceAlias') == physical for row in
                              (item['routes'] if isinstance(item['routes'], list) else [item['routes']]))
        for item in result.get('endpoint_routes', []))
    result['all_existing_connections_retained'] = (
        result['existing_connections_before'] > 0 and
        result['existing_connections_retained_during'] == result['existing_connections_before'] and
        result['existing_connections_retained_after'] == result['existing_connections_before'])
    result['gemini_noninterference_verified'] = False
    print(json.dumps(result, ensure_ascii=False))
    # 退出码仅代表这组有限双探针，不是Gemini/UDP或全量上线验收。
    return 0 if (result.get('system_during', {}).get('ok') and
                 result.get('socks_during', {}).get('ok') and result['business_unchanged'] and
                 result['endpoint_routes_physical'] and result['stop'].get('ok') and
                 result['personal_adapters_after'] == 0 and result['personal_routes_after'] == 0) else 2


if __name__ == '__main__':
    raise SystemExit(main())
