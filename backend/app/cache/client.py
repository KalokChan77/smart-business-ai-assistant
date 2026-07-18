from redis.asyncio import Redis


def create_redis_client(url: str) -> Redis:
    return Redis.from_url(
        url,
        decode_responses=True,
        health_check_interval=30,
    )
