from __future__ import annotations

import json
import time
from typing import Any, Dict

import requests

from .logging_utils import get_http_logger

HTTP_LOG = get_http_logger()

_PAYLOAD_TRIM = 500
_RESPONSE_TRIM = 800


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"...({len(text)} chars)"


class ApiClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()

    def post_json(
        self,
        path: str,
        headers: Dict[str, str],
        payload: Dict[str, Any],
        timeout: int = 20,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"

        payload_summary = _truncate(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            _PAYLOAD_TRIM,
        )
        HTTP_LOG.info(">>> POST %s  payload=%s", path, payload_summary)

        t0 = time.perf_counter()
        try:
            response = self.session.post(url, headers=headers, json=payload, timeout=timeout)
        except requests.RequestException as exc:
            elapsed = (time.perf_counter() - t0) * 1000
            HTTP_LOG.error("<<< POST %s  NETWORK_ERROR  %.0fms  %s", path, elapsed, exc)
            raise RuntimeError(f"网络请求失败: {exc}") from exc

        elapsed = (time.perf_counter() - t0) * 1000

        if response.status_code >= 400:
            snippet = _truncate(response.text.strip(), 300)
            HTTP_LOG.error(
                "<<< POST %s  HTTP_%d  %.0fms  body=%s",
                path, response.status_code, elapsed, snippet,
            )
            raise RuntimeError(f"上游接口 {response.status_code}: {snippet}")

        result = _decode_json_response(response)

        resp_summary = _truncate(
            json.dumps(result, ensure_ascii=False, separators=(",", ":")),
            _RESPONSE_TRIM,
        )
        success = result.get("success") if isinstance(result, dict) else None
        HTTP_LOG.info(
            "<<< POST %s  status=%d  success=%s  %.0fms  resp=%s",
            path, response.status_code, success, elapsed, resp_summary,
        )

        return result


def _decode_json_response(response: requests.Response) -> Dict[str, Any]:
    encodings = ["utf-8"]
    if response.apparent_encoding and response.apparent_encoding.lower() not in {"utf-8", "utf8"}:
        encodings.append(response.apparent_encoding)
    encodings.append("gb18030")

    last_error: Exception | None = None
    for encoding in encodings:
        try:
            text = response.content.decode(encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
            continue
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            last_error = exc
            continue

    snippet = response.content[:300]
    raise RuntimeError(f"上游接口返回非 JSON: {snippet!r}") from last_error
