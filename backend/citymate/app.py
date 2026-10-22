"""Application factory, resource lifecycle, middleware and router registration."""

import logging
import time
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from prometheus_client import CollectorRegistry, Counter, Histogram
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError

from .config import Settings
from .routers import ROUTERS
from .runtime import build


def create_app(settings=None, redis_client=None, platform=None):
    cfg = settings or Settings()
    p, engine = (platform, None) if platform else build(cfg, redis_client)
    cfg.uploads.mkdir(parents=True, exist_ok=True)
    registry = CollectorRegistry()
    requests = Counter(
        "citymate_requests_total", "HTTP requests", ["method", "route", "status"], registry=registry
    )
    latency = Histogram("citymate_request_seconds", "HTTP latency", ["route"], registry=registry)

    @asynccontextmanager
    async def lifespan(app):
        import os
        from .assistant import Assistant
        from .knowledge import Knowledge

        async with AsyncExitStack() as stack:
            mode = os.getenv("CITYMATE_KNOWLEDGE_TRANSPORT", "local")
            if mode == "mcp":
                import sys
                from mcp import StdioServerParameters
                from .knowledge_client import connect_knowledge

                env = {
                    k: v
                    for k, v in os.environ.items()
                    if k
                    in {
                        "PATH",
                        "SYSTEMROOT",
                        "TEMP",
                        "TMP",
                        "USERPROFILE",
                        "LOCALAPPDATA",
                        "CITYMATE_KNOWLEDGE_MODE",
                        "CITYMATE_KNOWLEDGE_CHUNK_SIZE",
                        "CITYMATE_KNOWLEDGE_CHUNK_OVERLAP",
                        "CITYMATE_CHROMA_PATH",
                    }
                }
                env["PYTHONIOENCODING"] = "utf-8"
                params = StdioServerParameters(
                    command=sys.executable,
                    args=["-m", "citymate.knowledge_server"],
                    cwd=str(Path(__file__).resolve().parents[1]),
                    env=env,
                )
                kb = await stack.enter_async_context(connect_knowledge(params))
            elif mode == "local":
                kb = Knowledge()
            else:
                raise ValueError("CITYMATE_KNOWLEDGE_TRANSPORT must be local or mcp")
            app.state.assistant = Assistant(p, kb)
            try:
                yield
            finally:
                if app.state.assistant.client:
                    await app.state.assistant.client.close()
                p.close()
                if engine:
                    p.r.close()
                    engine.dispose()

    app = FastAPI(title="CityMate · 城市生活助手", version="3.0.0", lifespan=lifespan)
    app.state.platform = p
    app.state.metrics_registry = registry
    app.mount("/uploads", StaticFiles(directory=cfg.uploads), name="uploads")

    @app.middleware("http")
    async def metrics(request, call_next):
        started = time.monotonic()
        # Cookie authentication needs CSRF protection. Cross-origin forms cannot
        # supply this header; cross-origin scripts require CORS, which is disabled.
        if (
            request.method in {"POST", "PUT", "PATCH", "DELETE"}
            and request.headers.get("x-citymate-request") != "1"
        ):
            return JSONResponse(status_code=403, content={"detail": "缺少请求校验标记"})
        response = await call_next(request)
        route = getattr(request.scope.get("route"), "path", "unmatched")
        requests.labels(request.method, route, response.status_code).inc()
        latency.labels(route).observe(time.monotonic() - started)
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(RedisError)
    @app.exception_handler(SQLAlchemyError)
    async def unavailable(request, exc):
        logging.getLogger(__name__).exception("Dependency failure", exc_info=exc)
        return JSONResponse(status_code=503, content={"detail": "数据服务暂不可用，请稍后重试"})

    for router in ROUTERS:
        app.include_router(router)
    return app


app = create_app()
