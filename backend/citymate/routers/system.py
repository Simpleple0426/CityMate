"""System HTTP endpoints."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from redis.exceptions import RedisError
from sqlalchemy import text
from ..dependencies import get_platform, require_admin

router = APIRouter(tags=["system"])


@router.get("/health")
def health(platform=Depends(get_platform)):
    platform.r.ping()
    with platform.db() as db:
        db.execute(text("SELECT 1 FROM cm_users LIMIT 1"))
    return {
        "status": "ok",
        "demo": platform.cfg.demo,
        "worker_online": bool(platform.r.exists(platform.key("worker-heartbeat"))),
        "ai_mode": "llm" if platform.cfg.api_key else "rules",
    }


@router.get("/metrics")
def metric_values(request: Request, _=Depends(require_admin)):
    return Response(
        generate_latest(request.app.state.metrics_registry), media_type=CONTENT_TYPE_LATEST
    )


@router.get("/admin/stats")
def stats(_=Depends(require_admin), platform=Depends(get_platform)):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    day = datetime.now(ZoneInfo(platform.cfg.timezone)).strftime("%Y%m%d")
    shops = platform.shops()
    try:
        pending = platform.r.xpending(platform.key("orders"), "order-workers")
    except RedisError:
        pending = {"pending": 0}
    return {
        "worker_online": bool(platform.r.exists(platform.key("worker-heartbeat"))),
        "pending": pending,
        "visitors": [
            {
                "shop": s["name"],
                "uv_approx": platform.r.pfcount(platform.key(f"uv:{s['id']}:{day}")),
            }
            for s in shops
        ],
    }
