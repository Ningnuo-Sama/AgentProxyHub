"""管理员预备回滚配置：只复制已验证的关闭TUN快照，不调用内核。"""
from __future__ import annotations
import hashlib
import os
import sys
from pathlib import Path
import yaml
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(r'D:\Program Files\AgentProxyHub\config')
TARGET = ROOT / 'rollback-disabled.yaml'

def validate(source: Path, runtime: Path) -> tuple[dict, str]:
    src = yaml.safe_load(source.read_text(encoding='utf-8-sig'))
    live = yaml.safe_load(runtime.read_text(encoding='utf-8-sig'))
    from core.personal_route import fixed_listener_map
    if (src.get('tun') or {}).get('enable', False):
        raise ValueError('rollback_snapshot_tun_must_be_disabled')
    if src.get('listeners') != live.get('listeners') or fixed_listener_map(src) != fixed_listener_map(live):
        raise ValueError('rollback_snapshot_business_mapping_mismatch')
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    return src, digest

def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print('usage: prepare_runtime_rollback.py <ProgramData snapshot>', file=sys.stderr)
        return 2
    source = Path(argv[1]).resolve()
    try:
        _, digest = validate(source, ROOT / 'config.yaml')
        tmp = TARGET.with_suffix('.tmp')
        data = source.read_bytes()
        tmp.write_bytes(data)
        os.replace(tmp, TARGET)
        print({'ok': True, 'target': str(TARGET), 'sha256': digest, 'tun_enabled': False})
        return 0
    except Exception as exc:
        print({'ok': False, 'code': type(exc).__name__, 'error': str(exc)}, file=sys.stderr)
        return 1

if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
