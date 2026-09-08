"""Bounded HTTPS JSON transport. Never includes URLs or response bodies in errors."""
import json
import os
import socket
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler, ProxyHandler


class APIError(RuntimeError):
    pass


def secret(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise APIError("missing credential: " + name)
    return value


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class HTTP:
    def __init__(self, sleep=time.sleep):
        self.opener = build_opener(ProxyHandler({}), NoRedirect())
        self.sleep = sleep

    def request(self, method, url, *, params=None, data=None, form=None, headers=None, retry=True):
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.username or parts.password:
            raise APIError("HTTPS required")
        if params:
            url += ("&" if "?" in url else "?") + urlencode(params)
        h = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36", "Accept": "application/json", **(headers or {})}
        payload = None
        if data is not None:
            payload = json.dumps(data).encode()
            h["Content-Type"] = "application/json"
        if form is not None:
            payload = urlencode(form).encode()
            h["Content-Type"] = "application/x-www-form-urlencoded"
        attempts = 3 if retry else 1
        for attempt in range(attempts):
            delay = 2 ** attempt
            try:
                with self.opener.open(Request(url, data=payload, headers=h, method=method), timeout=20) as response:
                    raw = response.read(4_000_001)
                    if len(raw) > 4_000_000:
                        raise APIError("response too large")
                    if not raw:
                        return {}
                    return json.loads(raw)
            except HTTPError as exc:
                status = exc.code
                retry_after = exc.headers.get("Retry-After", "")
                exc.close()
                if status not in (429, 500, 502, 503, 504) or attempt + 1 == attempts:
                    raise APIError("HTTP status " + str(status)) from None
                if retry_after:
                    try:
                        delay = max(delay, float(retry_after))
                    except ValueError:
                        raise APIError("unhandled rate-limit delay") from None
                    if not 0 <= delay <= 30:
                        raise APIError("rate-limit delay exceeds retry budget")
            except (URLError, TimeoutError, socket.timeout, ConnectionError):
                if attempt + 1 == attempts:
                    raise APIError("network failure") from None
            except (ValueError, UnicodeError):
                raise APIError("invalid JSON response") from None
            self.sleep(delay)
        raise APIError("retry budget exhausted")
