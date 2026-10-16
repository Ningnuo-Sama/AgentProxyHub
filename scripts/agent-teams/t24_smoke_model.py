#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t24 冒烟：模型路由指向本地 deepseek-v4.1（status + 一次最小 completion + 用量）。"""
from __future__ import annotations

import json
import sys

sys.path.insert(0, r"D:\Program Files\AgentProxyHub")

from core.model_router import complete, status  # noqa: E402


def main() -> int:
    st = status()
    print("--- model_router.status() ---")
    for row in st["models"]:
        print(f"  {row['role']:16s} provider={str(row.get('provider')):16s} model={str(row.get('model')):26s}"
              f" configured={row.get('configured')} sha12={row.get('credential_sha256_12')}"
              f" len={row.get('credential_len')} err={row.get('error')}")
    print(f"  chain={st['chain']}  media_handoff={st['media_handoff']}")

    print("--- complete(urgency=daily) 最小调用 ---")
    result = complete("只回复两个字：在线", urgency="daily",
                      system="你是 AgentProxyHub 驻场工程师，只做只读巡检，不做任何写动作。")
    print(json.dumps({k: v for k, v in result.items() if k != "usage"}, ensure_ascii=False)[:400])
    print("usage=" + json.dumps(result.get("usage") or {}, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
