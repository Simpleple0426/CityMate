"""Shops HTTP endpoints."""

from fastapi import APIRouter, Depends, Query
from ..dependencies import current_user, get_platform, require_admin
from ..schemas import ShopBody, VoucherBody
from ..service import fail

router = APIRouter(tags=["shops"])


@router.get("/categories")
def categories(platform=Depends(get_platform)):
    from sqlalchemy import select
    from ..models import Shop

    with platform.db() as db:
        return list(db.scalars(select(Shop.category).distinct().order_by(Shop.category)).all())


@router.get("/shops")
def shops(
    category: str = "",
    query: str = Query("", max_length=100),
    budget: int | None = Query(None, ge=0),
    longitude: float | None = Query(None, ge=-180, le=180),
    latitude: float | None = Query(None, ge=-85, le=85),
    radius: float = Query(10, gt=0, le=100),
    page: int = Query(1, ge=1, le=10000),
    platform=Depends(get_platform),
):
    if (longitude is None) != (latitude is None):
        fail(400, "经纬度需要一起提供")
    return platform.shops(category, query, budget, longitude, latitude, radius, page)


@router.get("/shops/{shop_id}")
def shop(shop_id: str, user=Depends(current_user), platform=Depends(get_platform)):
    return platform.shop(shop_id, user["id"])


@router.put("/admin/shops/{shop_id}")
def edit_shop(
    shop_id: str, body: ShopBody, _=Depends(require_admin), platform=Depends(get_platform)
):
    return platform.edit_shop(shop_id, body.model_dump())


@router.post("/admin/shops", status_code=201)
def create_shop(body: ShopBody, _=Depends(require_admin), platform=Depends(get_platform)):
    return platform.create_shop(body.model_dump())


@router.post("/admin/vouchers", status_code=201)
def create_voucher(body: VoucherBody, _=Depends(require_admin), platform=Depends(get_platform)):
    return platform.create_voucher(body.model_dump())


@router.get("/shops/{shop_id}/slots")
def slots(shop_id: str, platform=Depends(get_platform)):
    return platform.slots(shop_id)


@router.get("/vouchers")
def vouchers(shop_id: str | None = None, platform=Depends(get_platform)):
    return platform.vouchers(shop_id)
