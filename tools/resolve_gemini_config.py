"""Emit Gemini base URL and key for a local child process; never logs values."""
from __future__ import annotations
import json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
VAULT=Path(r'D:\ProgramData\AgentProxyHub\credentials\vault')
sys.path.insert(0,str(ROOT))
from core.credential_vault import _unprotect

def main():
 m=json.loads((VAULT/'manifest.json').read_text(encoding='utf-8'))
 for e in m.get('entries',[]):
  if e.get('category')=='gemini' and e.get('source_name')=='gemini3.8flash.txt':
   raw=_unprotect((VAULT/e['blob']).read_bytes()).decode('utf-8','replace').splitlines()
   if len(raw)>=2:
    base=raw[0].strip(); base=base if base.startswith('http') else 'http://127.0.0.1:8045'; base=base.removesuffix('/v1').rstrip('/')
    print(json.dumps({'base_url':base,'key':raw[1].strip()},separators=(',',':')))
    return 0
 return 1
if __name__=='__main__': raise SystemExit(main())
