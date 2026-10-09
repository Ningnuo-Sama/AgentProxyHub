"""MinerU 官方异步 OCR：隔离文件、分阶段请求、仅输出安全元数据。

契约核对：https://mineru.net/apiManage/docs（2026-10-03）。
不做轮询、重试、计费推断；不接受端点、凭据或隔离根覆盖。
"""
from __future__ import annotations

import hashlib
import io
import json
import requests
import os
from pathlib import Path, PurePosixPath
import re
import stat
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile

ROOT = Path(r"D:\360MoveData\Users\1\Desktop\新建文件夹 (2)")
API = "https://mineru.net"
UPLOAD_HOSTS = frozenset({"mineru.oss-cn-shanghai.aliyuncs.com", "oss-mineru.openxlab.org.cn"})
RESULT_HOSTS = frozenset({"cdn-mineru.openxlab.org.cn"})
MAX_RESULT = 64 * 1024 * 1024
MAX_EXPANDED = 128 * 1024 * 1024
TIMEOUT = 30
ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".jp2", ".webp", ".gif", ".bmp", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx"}


class OcrError(Exception):
    def __init__(self, code, **details):
        super().__init__(code)
        self.code, self.details = code, details


def _path(path, *, exists=True):
    root = ROOT.resolve(strict=True)
    candidate = Path(path)
    # 拒绝链接/junction、ADS、UNC 和所有逃逸，不依赖可被环境变量覆盖的根。
    if not candidate.is_absolute() or any(":" in p for p in candidate.parts[1:]):
        raise OcrError("ocr_path_not_allowed")
    resolved = candidate.resolve(strict=exists)
    if not resolved.is_relative_to(root) or resolved == root:
        raise OcrError("ocr_path_not_allowed")
    for component in (candidate, *candidate.parents):
        if component.exists():
            info = component.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise OcrError("ocr_path_not_allowed")
    return resolved


def _url(url, hosts):
    if not isinstance(url, str) or len(url) > 8192:
        raise OcrError("mineru_url_not_allowed")
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname not in hosts or parsed.port not in (None, 443)
            or parsed.username or parsed.password or parsed.fragment or "\\" in url):
        raise OcrError("mineru_url_not_allowed")
    return url


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise OcrError("mineru_redirect_refused")


def _request(method, url, *, headers=None, data=None, limit=1024 * 1024):
    # 禁用环境代理与重定向；上传/CDN请求不继承API鉴权。
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    started = time.monotonic()
    try:
        if method == "PUT":
            if hasattr(data, "read"):
                data = data.read(MAX_RESULT + 1)
            session = requests.Session()
            session.trust_env = False
            response = session.put(url, data=data, headers=headers or {}, allow_redirects=False, timeout=TIMEOUT)
            if response.status_code not in (200, 201):
                raise OcrError("mineru_http_error", http_status=response.status_code)
            return response.content
        if hasattr(data, "read"):
            data = data.read(MAX_RESULT if method == "PUT" else 1024 * 1024 * 1024)
        request = urllib.request.Request(url, data=data, method=method, headers=headers or {})
        with opener.open(request, timeout=TIMEOUT) as response:
            if response.status not in (200, 201):
                raise OcrError("mineru_http_error", http_status=response.status)
            chunks, count = [], 0
            while True:
                if time.monotonic() - started > TIMEOUT:
                    raise OcrError("mineru_timeout")
                chunk = response.read(min(65536, limit + 1 - count))
                if not chunk:
                    break
                count += len(chunk)
                if count > limit:
                    raise OcrError("mineru_response_too_large")
                chunks.append(chunk)
            return b"".join(chunks)
    except urllib.error.HTTPError as exc:
        status = exc.code
        exc.close()
        raise OcrError("mineru_http_error", http_status=status) from None
    except (TimeoutError, OSError, urllib.error.URLError):
        raise OcrError("mineru_network_error") from None


def _token():
    from core.credential_vault import MANIFEST, read_secret
    try:
        entries = json.loads(MANIFEST.read_text(encoding="utf-8"))["entries"]
        matches = [e for e in entries if Path(e.get("source_name", "")).name.lower() in ("mineru", "mineru.txt")]
        if len(matches) != 1:
            raise ValueError()
        raw = read_secret(matches[0]["id"]).decode("utf-8")
        # 仅接收独立密钥行（现场sk格式/JWT），不猜说明文档第一行；歧义拒绝。
        tokens = {line.strip() for line in raw.splitlines() if re.fullmatch(
            r"(?:sk-[A-Za-z0-9_-]{16,}|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)", line.strip())}
        if len(tokens) != 1:
            raise ValueError()
        return tokens.pop()
    except Exception:
        raise OcrError("mineru_credential_unavailable") from None


def _api(path, api, body=None):
    headers = {"Content-Type": "application/json"}
    if api == "precise":
        headers["Authorization"] = "Bearer " + _token()
    raw = _request("POST" if body is not None else "GET", API + path,
                   headers=headers, data=json.dumps(body).encode() if body is not None else None)
    try:
        payload = json.loads(raw)
        code = payload["code"]
        if type(code) is not int:
            raise ValueError()
        if code != 0:
            raise OcrError("mineru_api_error", provider_code=code)
        if not isinstance(payload["data"], dict):
            raise ValueError()
        return payload["data"]
    except (ValueError, KeyError, TypeError):
        raise OcrError("mineru_invalid_response") from None


def _id(value):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise OcrError("mineru_invalid_response")
    return value


def _save(path, data):
    path = _path(path, exists=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(data)
    return {"path": str(path), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def _results(data, api, job_id):
    url = data.get("full_zip_url" if api == "precise" else "markdown_url")
    raw = _request("GET", _url(url, RESULT_HOSTS), limit=MAX_RESULT)
    directory = _path(ROOT / "mineru-results" / job_id / uuid.uuid4().hex, exists=False)
    if api == "agent":
        raw.decode("utf-8")  # 无效编码不发布
        return [_save(directory / "full.md", raw)]
    artifacts, selected, names, total = [], [], set(), 0
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        if len(entries) > 1000:
            raise OcrError("mineru_unsafe_zip")
        for item in entries:
            name = item.orig_filename
            parts = PurePosixPath(name).parts
            mode = item.external_attr >> 16
            if (not parts or name.startswith("/") or "\\" in name or ":" in name
                    or any(p in ("..", ".") or p.endswith((".", " ")) for p in parts)
                    or any(p.split('.')[0].upper() in {"CON", "PRN", "AUX", "NUL", *("COM"+str(i) for i in range(1,10)), *("LPT"+str(i) for i in range(1,10))} for p in parts)
                    or stat.S_ISLNK(mode) or item.flag_bits & 1 or name.casefold() in names):
                raise OcrError("mineru_unsafe_zip")
            names.add(name.casefold())
            total += item.file_size
            if total > MAX_EXPANDED or item.file_size > MAX_RESULT or item.file_size > max(item.compress_size, 1) * 200:
                raise OcrError("mineru_unsafe_zip")
            if not item.is_dir() and Path(name).suffix.lower() in (".md", ".json"):
                selected.append(item)
        if not selected:
            raise OcrError("mineru_result_missing")
        # 完整校验与有界读取后再发布，防止恶意zip部分落盘。
        files = [(item.filename, archive.read(item)) for item in selected]
        for name, content in files:
            content.decode("utf-8")
        for name, content in files:
            artifacts.append(_save(directory.joinpath(*PurePosixPath(name).parts), content))
    return artifacts


def run(args):
    """MCP白名单输入输出；异常正文、远端消息和URL永不进入响应。"""
    base = {"provider": "mineru", "confidence": "unknown", "billing": "unknown", "executed": False}
    stage = "validate"
    try:
        if not isinstance(args, dict) or set(args) - {"action", "api", "file_path", "job_id"}:
            raise OcrError("ocr_invalid_arguments")
        action, api = args.get("action", "dry_run"), args.get("api", "precise")
        if action not in ("dry_run", "submit", "status") or api not in ("precise", "agent"):
            raise OcrError("ocr_invalid_arguments")
        if action == "status":
            if "file_path" in args or "api" in args:
                raise OcrError("ocr_invalid_arguments")
            job_id = args.get("job_id", "")
            if not isinstance(job_id, str) or not re.fullmatch(r"[a-f0-9]{32}", job_id):
                raise OcrError("ocr_invalid_job")
            job = json.loads(_path(ROOT / "mineru-jobs" / (job_id + ".json")).read_text(encoding="utf-8"))
            api, remote = job["api"], _id(job["remote_id"])
            if api not in ("precise", "agent"):
                raise OcrError("ocr_invalid_job")
            stage = "status"
            data = _api(("/api/v4/extract-results/batch/" if api == "precise" else "/api/v1/agent/parse/") + remote, api)
            if api == "precise":
                entries = data.get("extract_result")
                if not isinstance(entries, list) or len(entries) != 1 or not isinstance(entries[0], dict):
                    raise OcrError("mineru_invalid_response")
                data = entries[0]
            state = data.get("state")
            if state not in {"waiting-file", "pending", "running", "converting", "uploading", "done", "failed"}:
                raise OcrError("mineru_invalid_response")
            base.update(executed=True, job_id=job_id, status=state, source_sha256=job["source_sha256"],
                        model_version="vlm" if api == "precise" else "pipeline")
            if state == "failed":
                code = data.get("err_code")
                raise OcrError("mineru_task_failed", **({"provider_code": code} if type(code) is int else {}))
            if state == "done":
                stage = "download_result"
                base["artifacts"] = _results(data, api, job_id)
            return dict(base, ok=True, code="mineru_status")
        if "job_id" in args:
            raise OcrError("ocr_invalid_arguments")
        source = _path(args.get("file_path", ""))
        if not source.is_file() or source.suffix.lower() not in EXTENSIONS:
            raise OcrError("ocr_file_not_supported")
        size = source.stat().st_size
        if not 0 < size <= (10 if api == "agent" else 200) * 1024 * 1024:
            raise OcrError("ocr_file_too_large")
        with source.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        base.update(source_sha256=digest, source_bytes=size, api=api,
                    model_version="vlm" if api == "precise" else "pipeline")
        if action == "dry_run":
            return dict(base, ok=True, code="ocr_dry_run", status="not_submitted")
        job_id = uuid.uuid4().hex
        # 文件名用本地随机ID，不回传用户文件名或把它当远端标识。
        name = job_id + source.suffix.lower()
        body = ({"files": [{"name": name, "data_id": job_id, "is_ocr": True}], "model_version": "vlm"}
                if api == "precise" else {"file_name": name, "is_ocr": True})
        stage = "allocate_upload"
        data = _api("/api/v4/file-urls/batch" if api == "precise" else "/api/v1/agent/parse/file", api, body)
        remote = _id(data.get("batch_id" if api == "precise" else "task_id"))
        urls = data.get("file_urls") if api == "precise" else [data.get("file_url")]
        if not isinstance(urls, list) or len(urls) != 1:
            raise OcrError("mineru_invalid_response")
        stage = "upload"
        upload = _url(urls[0], UPLOAD_HOSTS)
        # API分配不等于submitted：仅PUT成功后记录可查询任务。
        source = _path(source)
        with source.open("rb") as handle:
            if hashlib.file_digest(handle, "sha256").hexdigest() != digest:
                raise OcrError("ocr_source_changed")
            handle.seek(0)
            # MinerU 官方示例对签名 PUT 只传 data，不自行补 Content-Length/Content-Type；
            # 由 urllib/OSS 处理请求 framing，避免签名头不匹配。
            _request("PUT", upload, headers={}, data=handle)
        _save(ROOT / "mineru-jobs" / (job_id + ".json"), json.dumps({"api": api, "remote_id": remote, "source_sha256": digest}).encode())
        return dict(base, ok=True, executed=True, code="mineru_submitted", status="submitted", job_id=job_id)
    except OcrError as exc:
        return dict(base, ok=False, code=exc.code, stage=stage, **exc.details)
    except Exception:
        return dict(base, ok=False, code="mineru_local_error", stage=stage)
