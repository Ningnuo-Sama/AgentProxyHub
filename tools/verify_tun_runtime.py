"""只读TUN运行验收：不切换配置、不启动/停止内核、不打印凭据。"""
from __future__ import annotations
import json
import socket
import subprocess
import urllib.request
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.tun_controller import TunController

FIXED = list(range(21001, 21081)) + list(range(22001, 22046))

def ps_json(command):
    p = subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',command],
                       capture_output=True, text=True, timeout=8)
    if p.returncode != 0:
        return None
    try: return json.loads(p.stdout)
    except (ValueError, TypeError): return None

def fixed_ports():
    bad=[]
    for port in FIXED:
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=.25): pass
        except OSError: bad.append(port)
    return {'count': len(FIXED), 'failed': bad}

def main():
    controller = TunController()
    state = controller.status()
    adapter = ps_json("Get-NetAdapter -Name Meta -ErrorAction SilentlyContinue | Select-Object Name,Status,InterfaceDescription | ConvertTo-Json -Compress")
    routes = ps_json("Get-NetRoute -ErrorAction SilentlyContinue | Where-Object {$_.InterfaceAlias -eq 'Meta' -and ($_.DestinationPrefix -eq '198.18.0.0/30' -or $_.DestinationPrefix -eq '0.0.0.0/5' -or $_.DestinationPrefix -eq '128.0.0.0/3')} | Select-Object DestinationPrefix,InterfaceAlias,NextHop | ConvertTo-Json -Compress")
    result={'controller':state,'meta_adapter':adapter,'tun_routes':routes,'fixed_ports':fixed_ports()}
    for name,url in [('domestic','http://www.baidu.com'),('overseas','https://www.google.com/generate_204')]:
        try:
            with urllib.request.urlopen(url, timeout=8) as r: result[name]={'ok':True,'status':r.status}
        except Exception as exc: result[name]={'ok':False,'error':type(exc).__name__}
    required = state.get('tun_enabled') is True and adapter and routes and not result['fixed_ports']['failed']
    # 国内必须成功；海外成功是全量出海的必要验收项，不隐藏超时。
    result['conclusion'] = 'tun_verified' if required and result['domestic'].get('ok') and result['overseas'].get('ok') else 'not_verified'
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result['conclusion']=='tun_verified' else 2

if __name__ == '__main__': raise SystemExit(main())
