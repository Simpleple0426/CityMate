"""Validated HTTP request models for the application."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Phone(Body):
    phone: str = Field(pattern=r"^1[3-9]\d{9}$")


class Login(Phone):
    code: str = Field(pattern=r"^\d{6}$")


class Profile(Body):
    nickname: str = Field(min_length=1, max_length=80)
    bio: str = Field(default="", max_length=500)


class Toggle(Body):
    enabled: bool


class NoteBody(Body):
    title: str = Field(min_length=1, max_length=100)
    body: str = Field(min_length=1, max_length=5000)
    shop_id: str | None = Field(default=None, max_length=40)
    images: list[str] = Field(default_factory=list, max_length=6)


class Draft(Body):
    shop_id: str = Field(max_length=40)
    slot: str = Field(pattern=r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")
    party_size: int = Field(ge=1, le=20)


class Review(Body):
    approve: bool
    reason: str = Field(default="", max_length=250)


class Chat(Body):
    message: str = Field(min_length=1, max_length=4000)
    conv_id: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]{1,64}$")


class ShopBody(Body):
    name: str = Field(min_length=1, max_length=120)
    category: str = Field(min_length=1, max_length=40)
    description: str = Field(min_length=1, max_length=3000)
    address: str = Field(min_length=1, max_length=250)
    longitude: float = Field(ge=-180, le=180)
    latitude: float = Field(ge=-85, le=85)
    price_cents: int = Field(ge=0, le=10000000)
    hours: str = Field(min_length=1, max_length=80)


class VoucherBody(Body):
    shop_id: str = Field(min_length=1, max_length=40)
    title: str = Field(min_length=1, max_length=160)
    rules: str = Field(min_length=1, max_length=3000)
    price_cents: int = Field(ge=0, le=10000000)
    stock: int = Field(ge=1, le=100000)
    starts_at: datetime
    ends_at: datetime
