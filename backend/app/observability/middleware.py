"""Records every request's route, status and duration, and tags its database work."""

import time

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.observability.metrics import REQUESTS
from app.observability.slow_queries import query_context


def route_template(scope: Scope) -> str | None:
    """The matched route with its prefixes: /api/v1/customers/{customer_id}.

    FastAPI keeps included routers nested, so the matched route's own path is relative to
    its router ("/customers/{customer_id}"). The prefixes are static, so the full template
    is the request path up to where the route's own pattern matches the rest.
    """
    route = scope.get("route")
    relative = getattr(route, "path", None)
    if relative is None:
        return None
    path = scope.get("path", "")
    pattern = getattr(route, "path_regex", None)
    if pattern is None:
        return relative
    for i, char in enumerate(path):
        if char == "/" and pattern.match(path[i:]):
            return path[:i] + relative
    return relative


class RequestMetricsMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        status = 500
        started = time.perf_counter()

        async def send_status(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        # Slow queries read the route from the scope once the router has matched it.
        token = query_context.set({"scope": scope})
        try:
            await self.app(scope, receive, send_status)
        finally:
            query_context.reset(token)
            # The route template (/api/v1/customers/{customer_id}), never the raw path, so
            # the number of series stays bounded.
            route = route_template(scope) or "unmatched"
            REQUESTS.observe(scope["method"], route, status, time.perf_counter() - started)
