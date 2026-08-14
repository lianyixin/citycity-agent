"""Security headers middleware: HSTS, X-Content-Type-Options, X-Frame-Options,
Referrer-Policy, and a permissive-but-safe CSP.

CSP allows inline styles/scripts because Vite injects them during build;
unsafe-inline is acceptable for this SPA shape. HSTS is only applied over HTTPS.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        # HSTS only over HTTPS (preview is HTTP, production is HTTPS)
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # Allow same-origin use of geolocation/camera/microphone. Empty allowlist
        # "()" fully disables the feature for the document (even after the user
        # grants browser permission), which broke the app's location feature.
        # "(self)" permits the site's own top-level page and same-origin frames.
        response.headers["Permissions-Policy"] = (
            "geolocation=(self), microphone=(self), camera=(self)"
        )
        return response
