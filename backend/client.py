from __future__ import annotations

import json
import time
from typing import Any, Dict

import requests

from .logging_utils import get_http_logger

HTTP_LOG = get_http_logger()


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
        HTTP_LOG.info(">>> POST %s", path)

        t0 = time.perf_counter()
        try:
            response = self.session.post(url, headers=headers, json=payload, timeout=timeout)
        except requests.RequestException:
            elapsed = (time.perf_counter() - t0) * 1000
            HTTP_LOG.error("<<< POST %s  NETWORK_ERROR  %.0fms", path, elapsed)
            raise RuntimeError("网络请求失败") from None

        elapsed = (time.perf_counter() - t0) * 1000

        if response.status_code >= 400:
            HTTP_LOG.error(
                "<<< POST %s  HTTP_%d  %.0fms",
                path, response.status_code, elapsed,
            )
            raise RuntimeError(f"上游接口 {response.status_code}")

        result = _decode_json_response(response)
        success = bool(result.get("success")) if isinstance(result, dict) else False
        HTTP_LOG.info(
            "<<< POST %s  status=%d  success=%s  %.0fms",
            path, response.status_code, success, elapsed,
        )

        return result


def _decode_json_response(response: requests.Response) -> Dict[str, Any]:
    encodings = ["utf-8"]
    if response.apparent_encoding and response.apparent_encoding.lower() not in {"utf-8", "utf8"}:
        encodings.append(response.apparent_encoding)
    encodings.append("gb18030")

    for encoding in encodings:
        try:
            text = response.content.decode(encoding)
        except UnicodeDecodeError:
            continue
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            continue

    raise RuntimeError("上游接口返回非 JSON") from None
