"""Community HTTP endpoints."""

import io
import re
from fastapi import APIRouter, Depends, File, Query, UploadFile
from PIL import Image, UnidentifiedImageError
from ..dependencies import current_user, get_platform
from ..schemas import NoteBody, Toggle
from ..service import fail, uid

router = APIRouter(tags=["community"])


@router.get("/users")
def people(user=Depends(current_user), platform=Depends(get_platform)):
    return platform.people(user["id"])


@router.put("/users/{target_id}/follow")
def follow(
    target_id: str, body: Toggle, user=Depends(current_user), platform=Depends(get_platform)
):
    return platform.follow(user["id"], target_id, body.enabled)


@router.get("/users/{target_id}/common")
def common(target_id: str, user=Depends(current_user), platform=Depends(get_platform)):
    return platform.common(user["id"], target_id)


@router.get("/notes")
def notes(
    page: int = Query(1, ge=1, le=10000), user=Depends(current_user), platform=Depends(get_platform)
):
    return platform.notes(user["id"], page)


@router.post("/notes")
def create_note(body: NoteBody, user=Depends(current_user), platform=Depends(get_platform)):
    for path in body.images:
        if (
            not re.fullmatch("/uploads/[a-f0-9]{32}\\.jpg", path)
            or not (platform.cfg.uploads / path.split("/")[-1]).is_file()
        ):
            fail(400, "图片必须先通过上传接口保存")
    return platform.create_note(user["id"], body.model_dump())


@router.put("/notes/{note_id}/like")
def like(note_id: str, body: Toggle, user=Depends(current_user), platform=Depends(get_platform)):
    return platform.like(user["id"], note_id, body.enabled)


@router.get("/feed")
def feed(
    cursor: str | None = Query(None, max_length=200),
    user=Depends(current_user),
    platform=Depends(get_platform),
):
    return platform.feed(user["id"], cursor)


@router.post("/uploads")
def upload(file: UploadFile = File(...), _=Depends(current_user), platform=Depends(get_platform)):
    raw = file.file.read(5 * 1024 * 1024 + 1)
    if len(raw) > 5 * 1024 * 1024:
        fail(413, "图片不能超过 5 MB")
    try:
        with Image.open(io.BytesIO(raw)) as image:
            if image.width * image.height > 20000000 or image.format not in {"JPEG", "PNG", "WEBP"}:
                fail(400, "仅支持不超过 2000 万像素的 JPEG、PNG、WebP 图片")
            image.load()
            image.thumbnail((1600, 1600))
            name = uid() + ".jpg"
            image.convert("RGB").save(platform.cfg.uploads / name, "JPEG", quality=88)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        fail(400, "图片内容无效")
    return {"url": "/uploads/" + name}


@router.get("/checkin")
def checkin_stats(user=Depends(current_user), platform=Depends(get_platform)):
    return platform.checkin_stats(user["id"])


@router.post("/checkin")
def checkin(user=Depends(current_user), platform=Depends(get_platform)):
    return platform.checkin(user["id"])


@router.get("/ranking")
def ranking(user=Depends(current_user), platform=Depends(get_platform)):
    return platform.ranking()
