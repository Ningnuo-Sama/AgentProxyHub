"""只读账号固定出口TLS基线；不输出账号/凭据，不换绑、不调用生成API。"""
import hashlib
import json
from pathlib import Path
import subprocess
from urllib.parse import urlsplit
from concurrent.futures import ThreadPoolExecutor

CONFIG = Path(r'C:\Users\1\.antigravity_tools\gui_config.json')


def bound_ports():
    raw = CONFIG.read_bytes()
    pool = json.loads(raw.decode('utf-8-sig'))['proxy']['proxy_pool']
    entries = {p['id']: p for p in pool['proxies']}
    ports = set()
    for identifier in pool['account_bindings'].values():
        entry = entries.get(identifier)
        if not entry or not entry.get('enabled'):
            raise ValueError('bound_proxy_unavailable')
        url = urlsplit(entry['url'])
        if url.scheme != 'socks5h' or url.hostname != '127.0.0.1' or url.username or url.password:
            raise ValueError('unexpected_bound_proxy')
        ports.add(url.port)
    return sorted(ports), hashlib.sha256(raw).hexdigest()


def probe_port(port):
    args = ['curl.exe', '--noproxy', '', '--socks5-hostname', f'127.0.0.1:{port}',
            '--connect-timeout', '4', '--max-time', '8', '-sS', '-o', 'NUL',
            '-w', '%{http_code}', 'https://www.google.com/generate_204']
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=10)
        return {'port': port, 'ok': p.returncode == 0 and p.stdout == '204',
                'exit': p.returncode, 'http': p.stdout, 'error': p.stderr.strip()[:120]}
    except subprocess.TimeoutExpired:
        return {'port': port, 'ok': False, 'error': 'bounded_timeout'}


def main():
    ports, digest = bound_ports()
    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(probe_port, ports))
    _, after = bound_ports()
    print(json.dumps({'ports': ports, 'results': results, 'config_unchanged': digest == after}, ensure_ascii=False))
    return 0 if all(r['ok'] for r in results) and digest == after else 2


if __name__ == '__main__':
    raise SystemExit(main())
