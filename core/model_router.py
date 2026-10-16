#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一文本模型路由：本地 deepseek-v4.1 主战、AT 网关 Gemini 次之、GLM 兜底、GPT 最高事态。

P2-4（2026-10-17）：主战模型改为**本地 deepseek-v4.1**（`http://127.0.0.1:2666/v1`，
模型 `cn:deepseek-v4.1-flash`，与用户「本地的你用的这个 deepseek4.1」同源）。
凭据只从环境变量 / DPAPI 金库 / DSH 运行时凭据文件短暂读取，不返回、不落盘、不打印；
调用摘要写入脱敏 usage ledger。媒体生成不在本模块范围内，媒体任务交给 Flow-Tools。
"""
from __future__ import annotations

import hashlib
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
    if kind in ("local", "local_huaiyuan"):
        return _local_credential()
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


def _policy_entry(role: str) -> dict[str, Any]:
    try:
        return dict(_policy().get(role) or {})
    except (OSError, ValueError):
        return {}


def _local_credential() -> tuple[str, str]:
    """本地 deepseek-v4.1（怀远网关 2666）凭据解析：**从不打印明文，只在内存中传递**。

    解析顺序（fail-open 到下一层，最终交给降级链）：
      1. 环境变量 `APHUB_LOCAL_LLM_KEY`（也接受 policy 的 `key_env` 指定的名字）
      2. APH 本机 DPAPI 金库中名称含 `huaiyuan` 的条目
      3. DSH 运行时凭据文件 `refs.HUAIYUAN_API_KEY`（与用户「本地的 deepseek4.1」同源）
    """
    entry = _policy_entry("daily")
    base = str(entry.get("base_url") or "http://127.0.0.1:2666/v1").rstrip("/")
    if not base.endswith("/v1"):
        base += "/v1"
    env_name = str(entry.get("key_env") or "APHUB_LOCAL_LLM_KEY")
    for candidate_env in (env_name, "APHUB_LOCAL_LLM_KEY"):
        value = os.environ.get(candidate_env)
        if value and value.strip():
            return base, value.strip()
    try:
        raw = _secret_by_name(str(entry.get("vault_name_match") or "huaiyuan")).decode("utf-8", "replace").strip()
        if raw:
            return base, raw.splitlines()[0].strip()
    except (KeyError, OSError, ValueError):
        pass
    value = _dsh_ref_key(str(entry.get("dsh_ref") or "HUAIYUAN_API_KEY"))
    if value:
        return base, value
    return base, ""


def _dsh_ref_key(ref_name: str) -> str:
    path = os.environ.get("APHUB_DSH_CREDENTIALS") or r"C:\Users\1\.dsh-beta\.credentials.yaml"
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(open(path, "r", encoding="utf-8")) or {}
    except (OSError, ValueError, ImportError):
        return ""
    value = ((data.get("refs") or {}).get(ref_name))
    return str(value).strip() if isinstance(value, str) else ""


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
    """执行一次非媒体文本任务。

    P2-4 降级链（写进 `config/model_policy.json` 的 `routing.chain`，此处兜底同值）：
      daily  → 本地 deepseek-v4.1（127.0.0.1:2666，loopback，近零流量）
      gemini → 本地 AT 网关（127.0.0.1:8045，DPAPI 凭据）
      fallback → 智谱 GLM（外网）
      critical → AICost GPT-6.1-SOL（付费，需人工确认）
    任一层失败自动落到下一层；**不因失败提高频率**（用户契约）。
    """
    if not prompt or len(prompt) > 12000:
        return {"ok": False, "code": "invalid_prompt"}
    policy = _policy()
    messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
    if urgency == "critical":
        chain = [("gpt", policy["highest_urgency"]["model"])]
    else:
        chain = [
            ("local", policy["daily"]["model"]),
            ("gemini", (policy.get("gemini") or {}).get("model") or policy["daily"].get("legacy_model") or "gemini-3.8-flash-tiered"),
            ("glm", policy["fallback"]["model"]),
        ]
    errors = []
    for index, (kind, model) in enumerate(chain):
        try:
            result = _provider(kind, model, messages)
            result["fallback_used"] = index > 0
            result["fallback_chain"] = [c[1] for c in chain]
            return result
        except Exception as exc:
            errors.append({"provider": kind, "model": model, "error": type(exc).__name__})
            record_usage(kind, model, status="error")
    return {"ok": False, "code": "model_chain_failed", "errors": errors, "paid_calls": False}


def status() -> dict[str, Any]:
    """只报「配置是否齐备」，**不返回任何凭据内容**（只给 sha256 前 12 位与长度）。"""
    policy = _policy()
    rows = []
    for key, kind in (("daily", "local"), ("gemini", "gemini"), ("fallback", "glm"), ("highest_urgency", "gpt")):
        item = policy.get(key) or {}
        try:
            base, credential = _credential(kind)
            rows.append({"role": key, "provider": item.get("provider"), "model": item.get("model"),
                         "base_url": item.get("base_url") or base, "configured": bool(credential),
                         "credential_sha256_12": hashlib.sha256(credential.encode("utf-8")).hexdigest()[:12] if credential else None,
                         "credential_len": len(credential)})
        except Exception as exc:
            rows.append({"role": key, "provider": item.get("provider"), "model": item.get("model"),
                         "configured": False, "error": type(exc).__name__})
    routing = policy.get("routing") or {}
    return {"ok": True, "models": rows, "chain": routing.get("chain") or ["daily", "gemini", "fallback"],
            "media_handoff": routing.get("media_handoff") or "flow_tools"}
