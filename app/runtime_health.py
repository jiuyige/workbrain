from redis import Redis

from app.config import CELERY_BROKER_URL

broker_client = Redis.from_url(
    CELERY_BROKER_URL,
    socket_connect_timeout=2,
    socket_timeout=2,
)


def check_broker_connection() -> None:
    broker_client.ping()
