#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一文本模型路由：Gemini 主战、GLM 兜底、GPT 最高事态。

凭据只从 DPAPI 金库短暂读取，不返回、不落盘；调用摘要写入脱敏 usage ledger。
媒体生成不在本模块范围内，媒体任务交给 Flow-Tools。
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Mapping

from .credential_vault import MANIFEST, read_secret
from .model_usage import record_response_usage, record_usage

POLICY_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "model_policy.json")


def _policy() -> dict[str, Any]:
    with open(POLICY_FILE, "r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def _secret_by_name(fragment: str, *, preferred_name: str | None = None) -> bytes:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    fragment = fragment.lower()
    entries = [e for e in manifest.get("entries", []) if fragment in str(e.get("source_name", "")).lower()]
    entry = next((e for e in entries if preferred_name and str(e.get("source_name", "")) == preferred_name), None) or (entries[0] if entries else None)
    if not entry:
        raise KeyError(f"credential_not_found:{fragment}")
    return read_secret(entry["id"])


def _credential(kind: str) -> tuple[str, str]:
    if kind == "gemini":
        raw = _secret_by_name("gemini3.8flash").decode("utf-8", "replace").splitlines()
        base = (raw[0].strip() if raw else "") or "http://127.0.0.1:8045"
        key = raw[1].strip() if len(raw) > 1 else ""
        base = base.rstrip("/")
        if base.endswith("/v1"):
            return base, key
        return base + "/v1", key
    if kind == "glm":
        raw = _secret_by_name(".txt", preferred_name="智谱决策专用.txt").decode("utf-8", "replace").strip().splitlines()
        return "https://open.bigmodel.cn/api/paas/v4", raw[-1].strip()
    if kind == "gpt":
        raw = _secret_by_name("aicost GPT6.1sol").decode("utf-8", "replace").strip()
        try:
            value = json.loads(raw)
            base = str(value.get("url") or "https://www.aicost.me").rstrip("/")
            if not base.endswith("/v1"):
                base += "/v1"
            return base, str(value.get("key") or "")
        except json.JSONDecodeError:
            return "https://www.aicost.me", raw.splitlines()[-1].strip()
    raise ValueError(kind)


def _post(base: str, key: str, model: str, messages: list[Mapping[str, str]], *, timeout: float = 30) -> dict[str, Any]:
    url = base.rstrip("/") + "/chat/completions"
    payload = json.dumps({"model": model, "messages": messages, "temperature": 0, "max_tokens": 800}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=payload, method="POST", headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


def _provider(kind: str, model: str, messages: list[Mapping[str, str]]) -> dict[str, Any]:
    base, key = _credential(kind)
    if not key:
        raise RuntimeError(f"{kind}_credential_empty")
    response = _post(base, key, model, messages)
    record_response_usage(kind, model, response, status="ok")
    choice = (response.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    return {"ok": True, "provider": kind, "model": model, "text": message.get("content", ""), "usage": response.get("usage", {})}


def complete(prompt: str, *, urgency: str = "daily", system: str | None = None) -> dict[str, Any]:
    """执行一次非媒体文本任务；daily 失败自动 GLM，critical 使用 GPT。"""
    if not prompt or len(prompt) > 12000:
        return {"ok": False, "code": "invalid_prompt"}
    policy = _policy()
    messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
    if urgency == "critical":
        chain = [("gpt", policy["highest_urgency"]["model"])]
    else:
        chain = [("gemini", policy["daily"]["model"]), ("glm", policy["fallback"]["model"])]
    errors = []
    for kind, model in chain:
        try:
            result = _provider(kind, model, messages)
            result["fallback_used"] = kind != chain[0][0]
            return result
        except Exception as exc:
            errors.append({"provider": kind, "model": model, "error": type(exc).__name__})
            record_usage(kind, model, status="error")
    return {"ok": False, "code": "model_chain_failed", "errors": errors, "paid_calls": urgency == "critical"}


def status() -> dict[str, Any]:
    policy = _policy()
    rows = []
    for key, kind in (("daily", "gemini"), ("fallback", "glm"), ("highest_urgency", "gpt")):
        item = policy[key]
        try:
            _base, credential = _credential(kind)
            rows.append({"role": key, "provider": item["provider"], "model": item["model"], "configured": bool(credential)})
        except Exception as exc:
            rows.append({"role": key, "provider": item["provider"], "model": item["model"], "configured": False, "error": type(exc).__name__})
    return {"ok": True, "models": rows, "media_handoff": "flow_tools"}
