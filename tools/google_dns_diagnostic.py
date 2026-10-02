"""只读对比固定SOCKS的本地/远端DNS和完整Google TLS；不换绑。"""
import json
import subprocess


def probe(mode, port=21012):
    command = ['curl.exe', '--noproxy', '', mode, f'127.0.0.1:{port}',
               '--connect-timeout', '5', '--max-time', '12', '-sS', '-o', 'NUL',
               '-w', '%{http_code} %{ssl_verify_result}', 'https://www.google.com/generate_204']
    try:
        p = subprocess.run(command, capture_output=True, text=True, timeout=15)
        fields = p.stdout.strip().split()
        return {'ok': p.returncode == 0 and fields == ['204', '0'],
                'exit': p.returncode, 'http_tls': fields,
                'error': p.stderr.strip()[:160]}
    except subprocess.TimeoutExpired:
        return {'ok': False, 'error': 'probe_timeout'}


def main():
    remote = probe('--socks5-hostname')
    local = probe('--socks5')
    print(json.dumps({'port': 21012, 'remote_dns': remote, 'local_dns': local,
                      'dns_path_difference_observed': remote['ok'] and not local['ok']}, ensure_ascii=False))
    return 0 if remote['ok'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
