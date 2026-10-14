"""The single place a Redis client is constructed. Everything that needs Redis (sessions, rate limiting and
later the plan store, RailRadar quota and conversation store) receives the client from the container."""

import logging

from redis import Redis

from app.config import Settings

log = logging.getLogger("railsaathi.redis")


def build_redis(settings: Settings) -> Redis | None:
    """Return a Redis client when REDIS_URL is set, else None (in-memory implementations are used).

    Connection is lazy: nothing is contacted here. Responses are decoded to str."""
    if not settings.redis_url:
        if settings.is_production:
            log.error("REDIS_URL is not set in production: sessions and rate limits are per-process only")
        return None
    return Redis.from_url(
        settings.redis_url, decode_responses=True,
        socket_timeout=settings.redis_socket_timeout_seconds,
        socket_connect_timeout=settings.redis_socket_timeout_seconds,
        health_check_interval=30,
    )
