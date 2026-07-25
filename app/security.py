"""Same-origin enforcement for state-changing requests.

The app has no authentication (see SECURITY.md), so without this any web page
the user happens to visit could drive it. A plain HTML form POST is a CORS
"simple request": the browser sends it cross-origin with no preflight and the
handler runs. Same-origin policy stops the attacker *reading* the response, but
not the write — so a single visited page could delete assets, rewrite values, or
POST a crafted CSV to /import/assets-csv.

Two checks close that off:

* ``SameOriginMiddleware`` rejects unsafe-method requests that the browser
  itself tells us originated elsewhere.
* ``AllowedHostMiddleware`` restricts which ``Host`` values are answered. That is
  what stops DNS rebinding: an attacker who points their own hostname at
  127.0.0.1 would otherwise sail through the origin check, because ``Origin`` and
  ``Host`` would agree with each other — and because the browser would then treat
  the app as same-origin, they could read responses too.

The host rule turns on names, not addresses. Rebinding needs a *hostname* whose
DNS the attacker controls; nobody can repoint a bare ``0.0.0.0``, ``127.0.0.1``,
``192.168.1.5`` or ``[::1]``. So every IP literal is accepted, ``localhost`` is
accepted, and any other hostname must be listed in ``ALLOWED_HOSTS`` (which is
what a reverse-proxy deployment configures). That keeps the whole protection
while never breaking someone who binds to an address and browses straight to it.

Non-browser clients (curl, the REST API, a future MCP server) send neither
``Sec-Fetch-Site`` nor ``Origin`` and are left alone; there is no cross-origin
context for them to be tricked from.
"""

import ipaddress
from urllib.parse import urlsplit

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import PlainTextResponse

from .config import settings

# Methods that must not change state, per RFC 9110, and so need no check.
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})

# Sec-Fetch-Site values that mean "not another site". "none" covers requests the
# user initiated directly (typed URL, bookmark), which no third party can forge.
_ALLOWED_FETCH_SITES = frozenset({"same-origin", "none"})


def is_same_origin(request: Request) -> bool:
    """Return True when the request did not demonstrably come from another site."""
    # Every current browser sends this, and it states the relationship outright.
    fetch_site = request.headers.get("sec-fetch-site")
    if fetch_site:
        return fetch_site in _ALLOWED_FETCH_SITES

    # Older browsers: fall back to Origin, which is always present on a
    # cross-origin POST. Compare hosts only — a TLS-terminating reverse proxy
    # legitimately changes the scheme, and it must pass the original Host
    # through (nginx: `proxy_set_header Host $host`) for this to line up.
    origin = request.headers.get("origin")
    if not origin:
        return True
    return urlsplit(origin).netloc == request.headers.get("host", "")


class SameOriginMiddleware(BaseHTTPMiddleware):
    """Reject state-changing requests that a browser reports as cross-origin."""

    async def dispatch(self, request: Request, call_next):
        if request.method not in SAFE_METHODS and not is_same_origin(request):
            return PlainTextResponse("Cross-origin request rejected.", status_code=403)
        return await call_next(request)


def hostname_of(host_header: str) -> str:
    """The bare host from a Host header value, without port or IPv6 brackets."""
    host = host_header.strip().lower()
    if host.startswith("["):  # [::1] or [::1]:8000
        closing = host.find("]")
        return host[1:closing] if closing != -1 else host[1:]
    if host.count(":") > 1:  # bare IPv6 with no port
        return host
    return host.split(":", 1)[0]


def is_allowed_host(host_header: str) -> bool:
    """Whether the app should answer a request carrying this Host header."""
    if "*" in settings.ALLOWED_HOSTS:
        return True

    host = hostname_of(host_header)
    if not host:
        return False

    # Always reachable locally, whatever ALLOWED_HOSTS says.
    if host == "localhost" or host.endswith(".localhost"):
        return True

    # Any IP literal. Not a rebinding risk: there is no name to repoint.
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        pass

    for entry in settings.ALLOWED_HOSTS:
        allowed = hostname_of(entry)
        if host == allowed:
            return True
        # "*.example.com" also matches "example.com" itself.
        if allowed.startswith("*.") and (
            host == allowed[2:] or host.endswith(allowed[1:])
        ):
            return True
    return False


def _describe(host_header: str) -> str:
    """A trimmed, control-character-free echo of the header, for the error body."""
    safe = "".join(c for c in host_header[:100] if c.isprintable())
    return safe or "(empty)"


class AllowedHostMiddleware(BaseHTTPMiddleware):
    """Answer only for IP literals, localhost, and hosts in ALLOWED_HOSTS."""

    async def dispatch(self, request: Request, call_next):
        host_header = request.headers.get("host", "")
        if not is_allowed_host(host_header):
            return PlainTextResponse(
                f"Host not allowed: {_describe(host_header)}\n\n"
                "Networa answers to any IP address and to localhost. Other "
                "hostnames must be listed explicitly, which is what prevents DNS "
                "rebinding against an app that has no authentication.\n\n"
                f"To allow this one, start it with:\n"
                f"    ALLOWED_HOSTS={_describe(host_header)}\n",
                status_code=400,
            )
        return await call_next(request)
