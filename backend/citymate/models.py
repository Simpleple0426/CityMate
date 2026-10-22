from datetime import datetime, timezone
from sqlalchemy import (
    String,
    Text,
    Integer,
    Float,
    DateTime,
    UniqueConstraint,
    ForeignKey,
    create_engine,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    __table_args__ = {
        "mysql_charset": "utf8mb4",
        "mysql_collate": "utf8mb4_unicode_ci",
        "mysql_engine": "InnoDB",
    }


class User(Base):
    __tablename__ = "cm_users"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    phone: Mapped[str] = mapped_column(String(20), unique=True)
    nickname: Mapped[str] = mapped_column(String(80))
    bio: Mapped[str] = mapped_column(String(500), default="")
    role: Mapped[str] = mapped_column(String(20), default="user")


class Shop(Base):
    __tablename__ = "cm_shops"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(40), index=True)
    description: Mapped[str] = mapped_column(Text)
    address: Mapped[str] = mapped_column(String(250))
    longitude: Mapped[float] = mapped_column(Float)
    latitude: Mapped[float] = mapped_column(Float)
    price_cents: Mapped[int] = mapped_column(Integer)
    hours: Mapped[str] = mapped_column(String(80))


class Voucher(Base):
    __tablename__ = "cm_vouchers"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    shop_id: Mapped[str] = mapped_column(ForeignKey("cm_shops.id"))
    title: Mapped[str] = mapped_column(String(160))
    rules: Mapped[str] = mapped_column(Text)
    price_cents: Mapped[int] = mapped_column(Integer)
    stock: Mapped[int] = mapped_column(Integer)
    starts_at: Mapped[datetime] = mapped_column(DateTime)
    ends_at: Mapped[datetime] = mapped_column(DateTime)


class Order(Base):
    __tablename__ = "cm_orders"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("cm_users.id"), index=True)
    voucher_id: Mapped[str] = mapped_column(ForeignKey("cm_vouchers.id"))
    purchase_key: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    status: Mapped[str] = mapped_column(String(30))
    price_cents: Mapped[int] = mapped_column(Integer)
    note: Mapped[str] = mapped_column(String(250), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Note(Base):
    __tablename__ = "cm_notes"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("cm_users.id"), index=True)
    shop_id: Mapped[str | None] = mapped_column(ForeignKey("cm_shops.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(100))
    body: Mapped[str] = mapped_column(Text)
    images: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Like(Base):
    __tablename__ = "cm_likes"
    user_id: Mapped[str] = mapped_column(ForeignKey("cm_users.id"), primary_key=True)
    note_id: Mapped[str] = mapped_column(ForeignKey("cm_notes.id"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Follow(Base):
    __tablename__ = "cm_follows"
    user_id: Mapped[str] = mapped_column(ForeignKey("cm_users.id"), primary_key=True)
    target_id: Mapped[str] = mapped_column(ForeignKey("cm_users.id"), primary_key=True)


class Checkin(Base):
    __tablename__ = "cm_checkins"
    user_id: Mapped[str] = mapped_column(ForeignKey("cm_users.id"), primary_key=True)
    day: Mapped[str] = mapped_column(String(10), primary_key=True)
    points: Mapped[int] = mapped_column(Integer, default=10)


class Appointment(Base):
    __tablename__ = "cm_appointments"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("cm_users.id"), index=True)
    shop_id: Mapped[str] = mapped_column(ForeignKey("cm_shops.id"))
    slot: Mapped[str] = mapped_column(String(40))
    party_size: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), default="draft")
    decision: Mapped[str] = mapped_column(String(250), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Slot(Base):
    __tablename__ = "cm_slots"
    shop_id: Mapped[str] = mapped_column(ForeignKey("cm_shops.id"), primary_key=True)
    label: Mapped[str] = mapped_column(String(40), primary_key=True)
    seats: Mapped[int] = mapped_column(Integer)


class Outbox(Base):
    __tablename__ = "cm_outbox"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    kind: Mapped[str] = mapped_column(String(40))
    payload: Mapped[str] = mapped_column(Text)
    done: Mapped[int] = mapped_column(Integer, default=0, index=True)


def database(url):
    engine = create_engine(
        url,
        pool_pre_ping=True,
        **(
            {"connect_args": {"check_same_thread": False, "timeout": 30}}
            if url.startswith("sqlite")
            else {}
        ),
    )
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def configure_sqlite(db, _):
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA journal_mode=WAL")

    return engine, sessionmaker(engine, expire_on_commit=False)


def public(row):
    return {
        c.name: (v.isoformat() if isinstance(v := getattr(row, c.name), datetime) else v)
        for c in row.__table__.columns
    }
