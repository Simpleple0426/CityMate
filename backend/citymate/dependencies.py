"""Request-scoped application services and authentication dependencies."""

from fastapi import Depends, Request, Response

from .config import Settings
from .service import fail


def get_platform(request: Request):
    """Resolve the services belonging to this application instance."""
    return request.app.state.platform


def current_user(request: Request, platform=Depends(get_platform)):
    """Authenticate the session and expose its user only within this request."""
    request.state.user = platform.authenticate(request.cookies.get(platform.cfg.session_cookie))
    return request.state.user


def require_admin(user=Depends(current_user)):
    if user["role"] != "admin":
        fail(403, "需要管理员权限")
    return user


def set_session_cookie(response: Response, session_id: str, settings: Settings):
    response.set_cookie(
        settings.session_cookie,
        session_id,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )
