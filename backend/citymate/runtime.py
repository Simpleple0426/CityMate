import redis
from .config import Settings
from .models import database
from .service import Core
from .commerce import Commerce
from .social import Social


class Platform(Commerce, Social, Core):
    pass


def build(settings=None, redis_client=None):
    settings = settings or Settings()
    engine, sessions = database(settings.database_url)
    client = redis_client or redis.Redis.from_url(
        settings.redis_url, decode_responses=True, socket_timeout=5, socket_connect_timeout=3
    )
    return Platform(settings, sessions, client), engine
