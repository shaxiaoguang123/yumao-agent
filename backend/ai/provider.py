from __future__ import annotations

import ipaddress
import json
import socket
import ssl
import time
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from http.client import HTTPSConnection, HTTPException
from typing import Callable, Mapping, Sequence
from urllib.parse import urlsplit, urlunsplit


class ProviderFailure(Exception):
    def __init__(self, code: str, status: int = 502):
        self.code, self.status = code, status
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    provider_id: str
    name: str
    base_url: str
    model: str
    auth_mode: str
    api_key: str | None = field(default=None, repr=False)
    version: int = 1
    source: str = "user"

    def public(self) -> dict:
        return {
            "id": self.provider_id, "name": self.name, "base_url": self.base_url,
            "model": self.model, "auth_mode": self.auth_mode,
            "has_api_key": bool(self.api_key), "version": self.version, "source": self.source,
        }


def validate_base_url(value: object) -> str:
    if (not isinstance(value, str) or not value or value != value.strip() or len(value) > 2048
        or any(ord(char) < 33 or ord(char) > 126 for char in value)):
        raise ProviderFailure("invalid_provider_config", 400)
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise ProviderFailure("invalid_provider_config", 400) from None
    if (parsed.scheme.lower() != "https" or not parsed.hostname or parsed.username is not None
        or parsed.password is not None or parsed.query or parsed.fragment or port not in (None, 443)):
        raise ProviderFailure("invalid_provider_config", 400)
    host = parsed.hostname.rstrip(".").lower()
    if not host or any(ord(c) < 33 for c in host):
        raise ProviderFailure("invalid_provider_config", 400)
    path = parsed.path or ""
    if "\\" in path or "%" in path or any(part in {".", ".."} for part in path.split("/")):
        raise ProviderFailure("invalid_provider_config", 400)
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
        if (not ip.is_global or ip.is_multicast or ip.is_reserved or ip.is_unspecified
            or ip.is_loopback or ip.is_link_local or ip.is_private or getattr(ip, 'is_site_local', False)
            or (isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None)):
            raise ProviderFailure("invalid_provider_config", 400)
    except ValueError:
        pass
    # Normalize only authority case and trailing slash; preserve a valid vendor prefix.
    authority = f'[{host}]' if ':' in host else host
    return urlunsplit(("https", authority, path.rstrip("/"), "", ""))


_DNS_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="ai-provider-dns")


def _get_addresses(host: str) -> list[str]:
    answers = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(item[4][0] for item in answers))


def _resolve_public(host: str, timeout: float = 2.0) -> list[str]:
    pending = _DNS_POOL.submit(_get_addresses, host)
    try:
        addresses = pending.result(timeout=timeout)
        if not addresses or len(addresses) > 16 or any(not _is_public_ip(ip) for ip in addresses):
            raise ProviderFailure("provider_address_rejected")
        return addresses
    except FutureTimeout:
        pending.cancel()
        raise ProviderFailure("provider_dns_timeout", 504) from None
    except ProviderFailure:
        raise
    except (OSError, ValueError):
        raise ProviderFailure("provider_unavailable") from None


def _is_public_ip(value: str) -> bool:
    ip = ipaddress.ip_address(value)
    return bool(ip.is_global and not (ip.is_multicast or ip.is_reserved or ip.is_unspecified
                    or ip.is_loopback or ip.is_link_local or ip.is_private or getattr(ip, 'is_site_local', False)
                    or (isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None)))


class _PinnedHTTPSConnection(HTTPSConnection):
    def __init__(self, host: str, pinned_ip: str, *, timeout: float, context: ssl.SSLContext):
        super().__init__(host, 443, timeout=timeout, context=context)
        self.pinned_ip = pinned_ip

    def connect(self):
        sock = socket.create_connection((self.pinned_ip, 443), self.timeout)
        try:
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except BaseException:
            sock.close()
            raise


class PinnedChatCompletionsTransport:
    """Direct TLS transport: vetted DNS set, pinned destination, no proxy or redirect."""

    def __init__(self, *, connect_timeout: float = 4, read_timeout: float = 15,
                 total_timeout: float = 30, max_response_bytes: int = 1_048_576,
                 resolver: Callable[[str], list[str]] = _resolve_public):
        self.connect_timeout, self.read_timeout = connect_timeout, read_timeout
        self.total_timeout, self.max_response_bytes, self.resolver = total_timeout, max_response_bytes, resolver

    def _request(self, config: ProviderConfig, messages: Sequence[Mapping[str, str]]) -> str:
        base = validate_base_url(config.base_url)
        parsed = urlsplit(base)
        deadline = time.monotonic() + self.total_timeout
        if self.resolver is _resolve_public:
            addresses = self.resolver(parsed.hostname or "", timeout=max(0.001, min(2.0, deadline - time.monotonic())))
        else:
            addresses = self.resolver(parsed.hostname or "")
        if time.monotonic() >= deadline:
            raise ProviderFailure("provider_timeout", 504)
        path = parsed.path.rstrip("/") + "/chat/completions"
        body = json.dumps({"model": config.model, "messages": list(messages), "max_tokens": 3072}, ensure_ascii=False,
                          separators=(",", ":")).encode("utf-8")
        if len(body) > 262_144:
            raise ProviderFailure("request_too_large", 413)
        headers = {"Content-Type": "application/json", "Accept": "application/json", "Connection": "close"}
        if config.auth_mode == "bearer":
            if not config.api_key:
                raise ProviderFailure("provider_not_configured", 409)
            headers["Authorization"] = "Bearer " + config.api_key
        if config.auth_mode not in {"bearer", "none"}:
            raise ProviderFailure("invalid_provider_config", 400)
        context = ssl.create_default_context()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ProviderFailure("provider_timeout", 504)
        # A POST is sent to one vetted address only; retrying another DNS answer
        # could duplicate a billed completion after an ambiguous network failure.
        conn = _PinnedHTTPSConnection(parsed.hostname or "", addresses[0], timeout=min(self.connect_timeout, remaining), context=context)
        timer: threading.Timer | None = None
        try:
            conn.connect()
            remaining = deadline - time.monotonic()
            if remaining <= 0 or conn.sock is None:
                raise ProviderFailure("provider_timeout", 504)
            # HTTPResponse can retain a socket file after HTTPSConnection clears
            # conn.sock for Connection: close. Keep the actual socket for aborting
            # blocked header/body reads; shutdown also wakes a file-backed reader.
            deadline_socket = conn.sock
            def abort_socket():
                try:
                    deadline_socket.shutdown(socket.SHUT_RDWR)
                except (OSError, AttributeError):
                    pass
                conn.close()
            timer = threading.Timer(remaining, abort_socket)
            timer.daemon = True
            timer.start()
            conn.sock.settimeout(min(self.read_timeout, remaining))
            conn.request("POST", path, body=body, headers=headers)
            response = conn.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                raise ProviderFailure("provider_redirect_rejected")
            chunks: list[bytes] = []
            total = 0
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ProviderFailure("provider_timeout", 504)
                if conn.sock is not None:
                    conn.sock.settimeout(min(self.read_timeout, remaining))
                chunk = response.read1(min(8192, self.max_response_bytes + 1 - total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                if total > self.max_response_bytes:
                    raise ProviderFailure("provider_response_too_large")
            if time.monotonic() > deadline:
                raise ProviderFailure("provider_timeout", 504)
            if response.status < 200 or response.status >= 300:
                category = {401:'provider_auth_failed',403:'provider_access_denied',
                            404:'provider_model_or_endpoint_not_found',429:'provider_rate_limited'}.get(response.status,'provider_request_failed')
                raise ProviderFailure(category)
            try:
                value = json.loads(b"".join(chunks).decode("utf-8"))
                content = value["choices"][0]["message"]["content"]
            except (ValueError, KeyError, IndexError, TypeError):
                raise ProviderFailure("provider_response_invalid") from None
            if not isinstance(content, str):
                raise ProviderFailure("provider_response_invalid")
            return content
        except ProviderFailure:
            raise
        except TimeoutError:
            raise ProviderFailure("provider_timeout", 504) from None
        except (OSError, ssl.SSLError, ValueError, HTTPException):
            if time.monotonic() >= deadline:
                raise ProviderFailure("provider_timeout", 504) from None
            raise ProviderFailure("provider_unavailable") from None
        finally:
            if timer is not None:
                timer.cancel()
            conn.close()

    def chat(self, config: ProviderConfig, messages: Sequence[Mapping[str, str]]) -> str:
        return self._request(config, messages)

    def test(self, config: ProviderConfig) -> bool:
        # Minimal non-sensitive prompt; endpoint errors are collapsed by caller.
        return isinstance(self._request(config, [{"role": "user", "content": "Reply with OK."}]), str)
