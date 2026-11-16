"""Redis helpers shared by the API and workers."""

from redis.asyncio import Redis

from officemates.core.health import CheckFn


def with_db(url: str, db: int) -> str:
    """Return ``url`` pointing at logical database ``db`` (replaces any existing /N path)."""
    base, _, query = url.partition("?")
    scheme, sep, rest = base.partition("://")
    host = rest.split("/", 1)[0]
    result = f"{scheme}{sep}{host}/{db}"
    return f"{result}?{query}" if query else result


def redis_readiness_check(url: str) -> CheckFn:
    async def check() -> None:
        client = Redis.from_url(url, socket_connect_timeout=1, socket_timeout=1)
        try:
            await client.ping()
        finally:
            await client.aclose()

    return check
