#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""网络自愈安全策略：仅同国决策，不写私库、不杀进程。"""
from typing import Any, Dict, Iterable, Optional
UNKNOWN={"","unknown","不明","fail","china","hong kong","macao","macau"}
def _norm(v): return " ".join(str(v or "").strip().casefold().split())
def same_region_candidate(dead:Dict[str,Any],candidates:Iterable[Dict[str,Any]])->Optional[Dict[str,Any]]:
    country=_norm(dead.get("country")); google=_norm(dead.get("googleCountry"))
    if country in UNKNOWN or google in UNKNOWN: return None
    eligible=[]
    for c in candidates:
        if c.get("IsBound"): continue
        if _norm(c.get("Country"))==country and _norm(c.get("GoogleCountry"))==google: eligible.append(c)
    return min(eligible,key=lambda c:c.get("Latency",10**9),default=None)
def can_restart_process(process,expected_name,expected_path):
    return bool(process) and int(process.get("pid",-1))>0 and _norm(process.get("name"))==_norm(expected_name) and str(process.get("path","")).rstrip("\\/").casefold()==str(expected_path).rstrip("\\/").casefold()
def restart_plan(process,expected_name,expected_path):
    verified=can_restart_process(process,expected_name,expected_path)
    return {"action":"restart" if verified else "escalate","verified":verified,"pid":process.get("pid") if verified else None,"reason":"精确 PID/名称/路径匹配" if verified else "身份不匹配，拒绝宽泛终止"}
