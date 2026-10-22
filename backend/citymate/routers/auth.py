"""Auth HTTP endpoints."""

from fastapi import APIRouter, Depends, Request, Response
from ..dependencies import current_user, get_platform, set_session_cookie
from ..schemas import Login, Phone, Profile
from ..service import fail

router = APIRouter(tags=["auth"])


@router.post("/auth/code")
def code(body: Phone, request: Request, response: Response, platform=Depends(get_platform)):
    ip = request.client.host if request.client else "unknown"
    key = platform.key("ip-code:" + ip)
    count = platform.r.incr(key)
    if count == 1:
        platform.r.expire(key, 600)
    if count > 20:
        fail(429, "请求过于频繁，请稍后再试")
    session_id, result = platform.code(body.phone)
    set_session_cookie(response, session_id, platform.cfg)
    response.headers["Cache-Control"] = "no-store"
    return result


@router.post("/auth/login")
def login(body: Login, request: Request, response: Response, platform=Depends(get_platform)):
    session_id, result = platform.login(
        body.phone, body.code, request.cookies.get(platform.cfg.session_cookie)
    )
    set_session_cookie(response, session_id, platform.cfg)
    response.headers["Cache-Control"] = "no-store"
    return result


@router.post("/auth/logout")
def logout(request: Request, response: Response, platform=Depends(get_platform)):
    platform.logout(request.cookies.get(platform.cfg.session_cookie))
    response.delete_cookie(
        platform.cfg.session_cookie,
        path="/",
        httponly=True,
        secure=platform.cfg.session_cookie_secure,
        samesite="lax",
    )
    return {"ok": True}


@router.get("/me")
def me(user=Depends(current_user)):
    return user


@router.put("/me")
def profile(body: Profile, user=Depends(current_user), platform=Depends(get_platform)):
    return platform.update_profile(user["id"], body.model_dump())
