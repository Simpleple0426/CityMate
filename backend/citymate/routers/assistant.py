"""Assistant HTTP endpoints."""

import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from ..dependencies import current_user
from ..schemas import Chat
from ..service import fail

router = APIRouter(tags=["assistant"])


@router.post("/chat")
async def chat(request: Request, body: Chat, user=Depends(current_user)):
    try:
        return await request.app.state.assistant.chat(user["id"], body.message, body.conv_id)
    except HTTPException:
        raise
    except Exception:
        logging.getLogger(__name__).exception("Assistant request failed")
        fail(503, "助手暂时不可用；仍可通过商户、优惠和订单页面操作")
