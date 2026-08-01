from __future__ import annotations

import logging
import json
import http.client
import ssl
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class MinerUBatchResult:
    batch_id: str
    full_zip_url: str


class MinerUError(RuntimeError):
    pass


logger = logging.getLogger(__name__)


def _request_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
    timeout_s: int = 60,
) -> dict[str, Any]:
    data: bytes | None = None
    req_headers = dict(headers or {})
    if json_body is not None:
        data = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
        req_headers.setdefault("Content-Type", "application/json")
    req_headers.setdefault("Accept", "application/json")

    req = urllib.request.Request(url=url, method=method, headers=req_headers, data=data)
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            payload = resp.read()
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        raise MinerUError(f"MinerU HTTP {e.code} {method} {url} {body}") from e
    except Exception as e:
        raise MinerUError(f"MinerU request failed {method} {url}: {e}") from e

    try:
        return json.loads(payload.decode("utf-8"))
    except Exception as e:
        raise MinerUError(f"MinerU returned non-JSON response: {payload[:2000]!r}") from e


def create_upload_batch(
    *,
    base_url: str,
    token: str,
    filename: str,
    model_version: str = "vlm",
    timeout_s: int = 60,
) -> tuple[str, str]:
    url = f"{base_url}/api/v4/file-urls/batch"
    resp = _request_json(
        "POST",
        url,
        headers={"Authorization": f"Bearer {token}"},
        json_body={"files": [{"name": filename}], "model_version": model_version},
        timeout_s=timeout_s,
    )

    if int(resp.get("code", -1)) != 0:
        raise MinerUError(f"MinerU create batch failed: {resp!r}")

    data = resp.get("data") or {}
    batch_id = data.get("batch_id") or ""
    file_urls = data.get("file_urls") or []
    if not batch_id or not file_urls:
        raise MinerUError(f"MinerU create batch missing fields: {resp!r}")

    return str(batch_id), str(file_urls[0])


def upload_file_to_presigned_url(*, file_path: str, upload_url: str, timeout_s: int = 600) -> None:
    file_path_obj = Path(file_path)
    if not file_path_obj.exists():
        raise FileNotFoundError(f"file not found: {file_path}")

    parsed = urllib.parse.urlsplit(upload_url)
    if parsed.scheme not in {"https", "http"}:
        raise MinerUError(f"unsupported upload url scheme: {parsed.scheme}")

    conn_cls = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    conn = conn_cls(parsed.hostname, parsed.port, timeout=timeout_s)

    try:
        path = urllib.parse.urlunsplit(("", "", parsed.path, parsed.query, parsed.fragment))
        content_length = file_path_obj.stat().st_size
        conn.putrequest("PUT", path)
        conn.putheader("Content-Length", str(content_length))
        conn.endheaders()
        with file_path_obj.open("rb") as f:
            while True:
                chunk = f.read(1024 * 1024)
                if not chunk:
                    break
                conn.send(chunk)
        resp = conn.getresponse()
        status = int(resp.status)
        if status >= 400:
            body = ""
            try:
                body = resp.read(2000).decode("utf-8", errors="replace")
            except Exception:
                body = ""
            raise MinerUError(f"MinerU upload failed: HTTP {status} {body}")
    except MinerUError:
        raise
    except Exception as e:
        raise MinerUError(f"MinerU upload failed: {e}") from e
    finally:
        try:
            conn.close()
        except Exception:
            pass


def poll_batch_result(
    *,
    base_url: str,
    token: str,
    batch_id: str,
    timeout_s: int = 1800,
    poll_interval_s: float = 2.0,
) -> MinerUBatchResult:
    url = f"{base_url}/api/v4/extract-results/batch/{urllib.parse.quote(batch_id)}"
    deadline = time.monotonic() + timeout_s
    last_state: str | None = None
    last_log_ts = 0.0

    while True:
        resp = _request_json("GET", url, headers={"Authorization": f"Bearer {token}"}, timeout_s=60)
        if int(resp.get("code", -1)) != 0:
            raise MinerUError(f"MinerU poll batch failed: {resp!r}")

        data = resp.get("data")
        item: dict[str, Any] = {}
        if isinstance(data, list) and data and isinstance(data[0], dict):
            item = data[0]
        elif isinstance(data, dict):
            if isinstance(data.get("results"), list) and data["results"] and isinstance(data["results"][0], dict):
                item = data["results"][0]
            elif isinstance(data.get("extract_results"), list) and data["extract_results"] and isinstance(data["extract_results"][0], dict):
                item = data["extract_results"][0]
            elif isinstance(data.get("extract_result"), list) and data["extract_result"] and isinstance(data["extract_result"][0], dict):
                item = data["extract_result"][0]
            else:
                item = data

        if item:
            state = str(item.get("state") or "")
            now = time.monotonic()
            if state != last_state or (now - last_log_ts) >= 15:
                progress = item.get("extract_progress") or {}
                extracted_pages = progress.get("extracted_pages")
                total_pages = progress.get("total_pages")
                if extracted_pages is not None and total_pages is not None:
                    logger.info(
                        "MinerU batch poll: batch_id=%s state=%s progress=%s/%s",
                        batch_id,
                        state,
                        extracted_pages,
                        total_pages,
                    )
                else:
                    logger.info("MinerU batch poll: batch_id=%s state=%s", batch_id, state)
                last_state = state
                last_log_ts = now
            if state == "done":
                full_zip_url = str(item.get("full_zip_url") or "")
                if not full_zip_url:
                    raise MinerUError(f"MinerU done but missing full_zip_url: {resp!r}")
                return MinerUBatchResult(batch_id=batch_id, full_zip_url=full_zip_url)
            if state == "failed":
                err_msg = str(item.get("err_msg") or "")
                raise MinerUError(f"MinerU parse failed: {err_msg}")
        else:
            now = time.monotonic()
            if (now - last_log_ts) >= 15:
                logger.info("MinerU batch poll: batch_id=%s state=unknown(empty_response)", batch_id)
                last_log_ts = now

        if time.monotonic() >= deadline:
            raise MinerUError(f"MinerU poll timeout after {timeout_s}s, batch_id={batch_id}")
        time.sleep(poll_interval_s)


def download_file(*, url: str, dst_path: str, timeout_s: int = 600) -> None:
    dst = Path(dst_path)
    dst.parent.mkdir(parents=True, exist_ok=True)

    ctx = ssl.create_default_context()
    last_err: Exception | None = None
    for attempt in range(1, 6):
        if dst.exists():
            try:
                dst.unlink()
            except Exception:
                pass
        req = urllib.request.Request(url=url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout_s, context=ctx) as resp:
                with dst.open("wb") as f:
                    while True:
                        chunk = resp.read(1024 * 1024)
                        if not chunk:
                            break
                        f.write(chunk)
            return
        except urllib.error.HTTPError as e:
            last_err = e
            if 500 <= int(e.code) < 600 and attempt < 5:
                time.sleep(min(2**attempt, 15))
                continue
            raise MinerUError(f"MinerU download failed HTTP {e.code}") from e
        except urllib.error.URLError as e:
            last_err = e
            retryable = False
            reason = getattr(e, "reason", None)
            if isinstance(reason, ssl.SSLError):
                retryable = True
            if isinstance(reason, socket.timeout):
                retryable = True
            if attempt < 5 and retryable:
                time.sleep(min(2**attempt, 15))
                continue
            raise MinerUError(f"MinerU download failed: {e}") from e
        except ssl.SSLError as e:
            last_err = e
            if attempt < 5:
                time.sleep(min(2**attempt, 15))
                continue
            raise MinerUError(f"MinerU download failed: {e}") from e
        except Exception as e:
            last_err = e
            if attempt < 5 and isinstance(e, (socket.timeout, ConnectionResetError)):
                time.sleep(min(2**attempt, 15))
                continue
            raise MinerUError(f"MinerU download failed: {e}") from e

    raise MinerUError(f"MinerU download failed after retries: {last_err}") from last_err
