"""Request correlation and request logging middleware."""

import logging
import re
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.errors import error_body
from app.core.logging import correlation_id_var

CORRELATION_HEADER = "X-Correlation-ID"
# Accept caller-supplied IDs only when they are short and log-safe.
_VALID_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")

logger = logging.getLogger("atlas.request")


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        supplied = request.headers.get(CORRELATION_HEADER)
        correlation_id = supplied if supplied and _VALID_ID.match(supplied) else str(uuid.uuid4())
        token = correlation_id_var.set(correlation_id)
        started = time.perf_counter()
        try:
            try:
                response = await call_next(request)
            except Exception:
                # Handled here (not only by the app's exception handler) so the error body
                # and header still carry the correlation ID.
                logger.exception("Unhandled error", extra={"path": request.url.path})
                response = JSONResponse(
                    status_code=500,
                    content=error_body("internal_error", "An unexpected error occurred."),
                )
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            response.headers[CORRELATION_HEADER] = correlation_id
            logger.info(
                "request completed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                },
            )
            return response
        finally:
            correlation_id_var.reset(token)
