"""Commerce HTTP endpoints."""

from fastapi import APIRouter, Depends
from ..dependencies import current_user, get_platform, require_admin
from ..schemas import Draft, Review

router = APIRouter(tags=["commerce"])


@router.post("/vouchers/{voucher_id}/claim", status_code=202)
def claim(voucher_id: str, user=Depends(current_user), platform=Depends(get_platform)):
    return platform.claim(user["id"], voucher_id)


@router.get("/orders")
def orders(user=Depends(current_user), platform=Depends(get_platform)):
    return platform.orders(user["id"])


@router.get("/orders/{order_id}")
def order(order_id: str, user=Depends(current_user), platform=Depends(get_platform)):
    return platform.order(user["id"], order_id)


@router.post("/orders/{order_id}/cancel")
def cancel(order_id: str, user=Depends(current_user), platform=Depends(get_platform)):
    return platform.cancel_order(user["id"], order_id)


@router.post("/appointments/drafts")
def draft(body: Draft, user=Depends(current_user), platform=Depends(get_platform)):
    return platform.draft_appointment(user["id"], **body.model_dump())


@router.post("/appointments/{draft_id}/confirm")
def confirm(draft_id: str, user=Depends(current_user), platform=Depends(get_platform)):
    return platform.confirm_appointment(user["id"], draft_id)


@router.get("/appointments")
def appointments(user=Depends(current_user), platform=Depends(get_platform)):
    return platform.appointments(user["id"])


@router.get("/admin/appointments")
def all_appointments(_=Depends(require_admin), platform=Depends(get_platform)):
    return platform.appointments()


@router.post("/admin/appointments/{appointment_id}/review")
def review(
    appointment_id: str, body: Review, _=Depends(require_admin), platform=Depends(get_platform)
):
    return platform.review(appointment_id, body.approve, body.reason)
