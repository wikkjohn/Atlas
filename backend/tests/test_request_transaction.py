"""A request's transaction ends before its response is sent (found in Phase 16)."""

import asyncio
from collections.abc import Iterator

from app.core.database import get_db
from app.core.dependencies import DbSession
from app.main import create_app


def test_the_transaction_commits_before_the_response_is_sent() -> None:
    events: list[str] = []
    app = create_app()

    def recording_db() -> Iterator[object]:
        yield object()
        events.append("commit")  # where get_db commits

    app.dependency_overrides[get_db] = recording_db

    @app.post("/_test/write")
    def write(db: DbSession) -> dict:
        events.append("endpoint")
        return {}

    async def call() -> None:
        async def receive() -> dict:
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message: dict) -> None:
            if message["type"] == "http.response.start":
                events.append("response")

        scope = {
            "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
            "method": "POST", "scheme": "http", "path": "/_test/write",
            "raw_path": b"/_test/write", "query_string": b"", "root_path": "",
            "headers": [(b"host", b"test")], "client": ("127.0.0.1", 0),
            "server": ("test", 80),
        }  # fmt: skip
        await app(scope, receive, send)

    asyncio.run(call())
    assert events == ["endpoint", "commit", "response"]
