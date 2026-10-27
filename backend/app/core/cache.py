"""Optional Redis connectivity (caching and lightweight queues in later phases)."""

from dataclasses import dataclass

import redis


@dataclass(frozen=True)
class RedisHealth:
    status: str  # "ok" | "unavailable" | "disabled"
    error: str | None = None


def check_redis(redis_url: str | None) -> RedisHealth:
    if not redis_url:
        return RedisHealth(status="disabled")
    client = redis.Redis.from_url(redis_url, socket_connect_timeout=1, socket_timeout=1)
    try:
        client.ping()
    except redis.RedisError as exc:
        return RedisHealth(status="unavailable", error=str(exc))
    finally:
        client.close()
    return RedisHealth(status="ok")
