#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""受限地区红线（送中判定）单一事实来源 (Blocked Regions).

背景：
    Google 判定国为 China / Hong Kong / Macao 时，Antigravity、Gemini、Flow 等
    AI 业务一律返回 400 FAILED_PRECONDITION「User location is not supported for the API use.」

历史缺陷：
    自愈链路（confidence_engine / hot_swap_executor）过去只把 `china` 视为送中，
    导致「澳门（Macao）」被判定为健康出口。2026-10-10 自愈系统因此在发现送中后，
    把 21015/21017/21022/21054/21063/22007 六个端口集体"治愈"到澳门节点 fw-21025，
    反而制造了更大范围的锁区事故。

契约：
    本模块是唯一判定入口。任何新增的受限地区只在此处维护，
    禁止在其他模块内散落 `== "china"` 之类的字面量比较。
"""
from __future__ import annotations

from typing import Any

#: Google 判定国命中即视为不可用（锁区）的名称集合（统一小写、空格归一）。
BLOCKED_GOOGLE_COUNTRIES = frozenset({
    "china",
    "hong kong",
    "hongkong",
    "hong-kong",
    "macao",
    "macau",
    "mainland china",
})

#: 便于审计与日志展示的稳定顺序。
BLOCKED_COUNTRIES_LABEL = "China / Hong Kong / Macao"


def normalize_country(name: Any) -> str:
    """把 Google 判定国归一化为可比较的小写名称。"""
    if name is None:
        return ""
    text = str(name).strip().lower()
    for sep in ("_", "-"):
        text = text.replace(sep, " ")
    return " ".join(text.split())


def is_blocked_google_country(name: Any) -> bool:
    """Google 判定国是否落在锁区红线内。"""
    return normalize_country(name) in BLOCKED_GOOGLE_COUNTRIES
