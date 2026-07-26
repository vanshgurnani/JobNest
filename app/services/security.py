import ipaddress
import re
import time
from collections import defaultdict
from typing import Any

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.config import get_settings


_PRIVATE_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
]

_FORBIDDEN_HOSTNAMES = re.compile(
    r"^(localhost|127\.\d+\.\d+\.\d+|0\.0\.0\.0|"
    r"169\.254\.169\.254|10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|172\.1[6-9]\.\d+\.\d+|"
    r"172\.2[0-9]\.\d+\.\d+|172\.3[0-1]\.\d+\.\d+)$",
    re.IGNORECASE,
)

_HOSTNAME_BLOCKLIST = re.compile(
    r"(\.internal$|\.local$|^metadata\.|\.internal\.|^internal\.)",
    re.IGNORECASE,
)

_MAX_URL_LENGTH = 2048


def is_safe_url(url: str) -> tuple[bool, str]:
    if len(url) > _MAX_URL_LENGTH:
        return False, "URL exceeds maximum length"
    if not url.startswith(("http://", "https://")):
        return False, "Only http/https URLs are allowed"

    host = url.split("/")[2].lower() if "://" in url else ""
    host = host.split(":")[0]

    if _FORBIDDEN_HOSTNAMES.match(host):
        return False, "URL targets a restricted host"

    if _HOSTNAME_BLOCKLIST.search(host):
        return False, "URL targets an internal network hostname"

    if "." not in host:
        return False, "URL uses a bare hostname which may resolve to a private address"

    try:
        ip = ipaddress.ip_address(host)
        for block in _PRIVATE_NETWORKS:
            if ip in block:
                return False, "URL targets a private network address"
    except ValueError:
        pass

    return True, ""


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: Any):
        super().__init__(app)
        self._requests: dict[str, list[float]] = defaultdict(list)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        settings = get_settings()
        if settings.rate_limit_requests <= 0:
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        now = time.time()
        window = settings.rate_limit_window_seconds
        window_start = now - window

        ip_requests = self._requests[client_ip]
        ip_requests[:] = [t for t in ip_requests if t > window_start]

        if len(ip_requests) >= settings.rate_limit_requests:
            return Response(
                status_code=429,
                content='{"detail":"Rate limit exceeded. Try again later."}',
                media_type="application/json",
                headers={"Retry-After": str(int(window))},
            )

        ip_requests.append(now)
        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "0"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "font-src 'self'; "
            "connect-src 'self'"
        )
        return response
