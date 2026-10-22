import os
from dataclasses import dataclass, field
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Settings:
    database_url: str = field(
        default_factory=lambda: os.getenv("CITYMATE_DATABASE_URL", "sqlite:///./citymate.sqlite3")
    )
    redis_url: str = field(
        default_factory=lambda: os.getenv("CITYMATE_REDIS_URL", "redis://localhost:6379/2")
    )
    demo: bool = field(
        default_factory=lambda: os.getenv("CITYMATE_DEMO", "false").lower() == "true"
    )
    uploads: Path = field(
        default_factory=lambda: Path(os.getenv("CITYMATE_UPLOADS", "./data/citymate/uploads"))
    )
    cache_mode: str = field(default_factory=lambda: os.getenv("CITYMATE_CACHE_MODE", "mutex"))
    timezone: str = "Asia/Shanghai"
    prefix: str = "citymate:{citymate}:"
    session_ttl: int = 1800
    session_cookie: str = "citymate_session"
    session_cookie_secure: bool = field(
        default_factory=lambda: os.getenv("CITYMATE_COOKIE_SECURE", "false").lower() == "true"
    )
    api_key: str = field(
        default_factory=lambda: (
            os.getenv("OPENAI_API_KEY", "")
            if os.getenv("CITYMATE_MODEL_ENABLED", "true").lower() == "true"
            else ""
        )
    )
    model: str = field(default_factory=lambda: os.getenv("OPENAI_MODEL", "gpt-4o-mini"))
    base_url: str | None = field(default_factory=lambda: os.getenv("OPENAI_BASE_URL") or None)
