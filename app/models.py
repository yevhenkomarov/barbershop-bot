from datetime import date, datetime, time

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Table,
    Text,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


BOOKING = "booking"
BLOCK = "block"
ACTIVE = "active"
CANCELLED = "cancelled"
SRC_BOT = "bot"
SRC_ADMIN = "admin"
BY_CLIENT = "client"
BY_ADMIN = "admin"


master_services = Table(
    "master_services",
    Base.metadata,
    Column("master_id", ForeignKey("masters.id", ondelete="CASCADE"), primary_key=True),
    Column("service_id", ForeignKey("services.id", ondelete="CASCADE"), primary_key=True),
)


class Service(Base):
    __tablename__ = "services"
    __table_args__ = (
        CheckConstraint("duration_min > 0", name="services_duration_positive"),
        CheckConstraint("price >= 0", name="services_price_nonneg"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    short_name: Mapped[str] = mapped_column(String(40))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    duration_min: Mapped[int] = mapped_column(Integer)
    price: Mapped[int] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(default=True, server_default="true")
    sort_order: Mapped[int] = mapped_column(default=0, server_default="0")


class Master(Base):
    __tablename__ = "masters"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(60))
    tg_username: Mapped[str | None] = mapped_column(String(64))
    tg_user_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    note: Mapped[str] = mapped_column(Text, default="", server_default="")
    is_active: Mapped[bool] = mapped_column(default=True, server_default="true")
    sort_order: Mapped[int] = mapped_column(default=0, server_default="0")

    services: Mapped[list[Service]] = relationship(
        secondary=master_services, lazy="selectin", order_by=Service.sort_order
    )


class WeeklyShift(Base):
    __tablename__ = "weekly_shifts"
    __table_args__ = (
        UniqueConstraint("master_id", "weekday", name="weekly_shifts_master_weekday"),
        CheckConstraint("weekday BETWEEN 0 AND 6", name="weekly_shifts_weekday_range"),
        CheckConstraint("end_time > start_time", name="weekly_shifts_end_after_start"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    master_id: Mapped[int] = mapped_column(ForeignKey("masters.id", ondelete="CASCADE"))
    weekday: Mapped[int] = mapped_column(SmallInteger)
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)


class ShiftOverride(Base):
    __tablename__ = "shift_overrides"
    __table_args__ = (
        UniqueConstraint("master_id", "day", name="shift_overrides_master_day"),
        CheckConstraint(
            "(start_time IS NULL AND end_time IS NULL) OR (start_time IS NOT NULL AND end_time > start_time)",
            name="shift_overrides_valid",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    master_id: Mapped[int] = mapped_column(ForeignKey("masters.id", ondelete="CASCADE"))
    day: Mapped[date] = mapped_column(Date)
    start_time: Mapped[time | None] = mapped_column(Time)
    end_time: Mapped[time | None] = mapped_column(Time)
    note: Mapped[str] = mapped_column(Text, default="", server_default="")


class Vacation(Base):
    __tablename__ = "vacations"
    __table_args__ = (CheckConstraint("date_to >= date_from", name="vacations_range_valid"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    master_id: Mapped[int] = mapped_column(ForeignKey("masters.id", ondelete="CASCADE"))
    date_from: Mapped[date] = mapped_column(Date)
    date_to: Mapped[date] = mapped_column(Date)
    note: Mapped[str] = mapped_column(Text, default="", server_default="")


class Client(Base):
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(primary_key=True)
    tg_user_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    tg_username: Mapped[str | None] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(100), default="", server_default="")
    phone: Mapped[str | None] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Booking(Base):
    __tablename__ = "bookings"
    __table_args__ = (
        CheckConstraint("ends_at > starts_at", name="bookings_end_after_start"),
        CheckConstraint("kind IN ('booking', 'block')", name="bookings_kind_valid"),
        CheckConstraint("status IN ('active', 'cancelled')", name="bookings_status_valid"),
        CheckConstraint(
            "kind = 'block' OR (service_id IS NOT NULL AND client_id IS NOT NULL)",
            name="bookings_booking_has_client",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(10), default=BOOKING)
    status: Mapped[str] = mapped_column(String(10), default=ACTIVE)
    master_id: Mapped[int] = mapped_column(ForeignKey("masters.id"), index=True)
    service_id: Mapped[int | None] = mapped_column(ForeignKey("services.id"))
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id"), index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    price: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(10), default=SRC_BOT)
    note: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_by: Mapped[str | None] = mapped_column(String(10))
    remind_24_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    remind_2_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    master: Mapped[Master] = relationship(lazy="joined", innerjoin=True)
    service: Mapped[Service | None] = relationship(lazy="joined")
    client: Mapped[Client | None] = relationship(lazy="joined")
