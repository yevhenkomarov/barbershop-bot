from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.availability import Availability, Busy, MasterSchedule, Shift
from app.models import (
    ACTIVE,
    BLOCK,
    BOOKING,
    BY_CLIENT,
    CANCELLED,
    SRC_BOT,
    Booking,
    Client,
    Master,
    Service,
    ShiftOverride,
    Vacation,
    WeeklyShift,
    master_services,
)


class SlotTaken(Exception):
    pass


class CancelNotAllowed(Exception):
    pass


def now_utc() -> datetime:
    return datetime.now(UTC)


def local_now() -> datetime:
    return datetime.now(get_settings().tz)


def day_bounds_utc(d_from: date, d_to: date) -> tuple[datetime, datetime]:
    tz = get_settings().tz
    start = datetime.combine(d_from, time(0), tzinfo=tz).astimezone(UTC)
    end = datetime.combine(d_to + timedelta(days=1), time(0), tzinfo=tz).astimezone(UTC)
    return start, end


def booking_days(now: datetime | None = None) -> list[date]:
    s = get_settings()
    today = (now or now_utc()).astimezone(s.tz).date()
    return [today + timedelta(days=i) for i in range(s.booking_days_ahead)]


def is_exclusion_violation(err: IntegrityError) -> bool:
    orig = err.orig
    for obj in (orig, getattr(orig, "__cause__", None)):
        if obj is not None and getattr(obj, "sqlstate", None) == "23P01":
            return True
    return "bookings_no_overlap" in str(err)


async def active_services(session: AsyncSession) -> Sequence[Service]:
    q = select(Service).where(Service.is_active).order_by(Service.sort_order, Service.id)
    return (await session.scalars(q)).all()


async def capable_masters(session: AsyncSession, service_id: int) -> Sequence[Master]:
    q = (
        select(Master)
        .join(master_services, master_services.c.master_id == Master.id)
        .where(master_services.c.service_id == service_id, Master.is_active)
        .order_by(Master.sort_order, Master.id)
    )
    return (await session.scalars(q)).all()


async def load_availability(
    session: AsyncSession,
    master_ids: Sequence[int],
    d_from: date,
    d_to: date,
    *,
    now: datetime | None = None,
    lead_min: int | None = None,
) -> Availability:
    s = get_settings()
    ids = list(master_ids)
    schedules: dict[int, MasterSchedule] = {mid: MasterSchedule() for mid in ids}
    if ids:
        for ws in await session.scalars(select(WeeklyShift).where(WeeklyShift.master_id.in_(ids))):
            schedules[ws.master_id].weekly[ws.weekday] = Shift(ws.start_time, ws.end_time)
        q_ov = select(ShiftOverride).where(
            ShiftOverride.master_id.in_(ids), ShiftOverride.day >= d_from, ShiftOverride.day <= d_to
        )
        for ov in await session.scalars(q_ov):
            shift = Shift(ov.start_time, ov.end_time) if ov.start_time and ov.end_time else None
            schedules[ov.master_id].overrides[ov.day] = shift
        q_vac = select(Vacation).where(
            Vacation.master_id.in_(ids), Vacation.date_from <= d_to, Vacation.date_to >= d_from
        )
        for v in await session.scalars(q_vac):
            schedules[v.master_id].vacations.append((v.date_from, v.date_to))
        start, end = day_bounds_utc(d_from, d_to)
        q_b = select(Booking.master_id, Booking.starts_at, Booking.ends_at, Booking.kind).where(
            Booking.master_id.in_(ids),
            Booking.status == ACTIVE,
            Booking.starts_at < end,
            Booking.ends_at > start,
        )
        for mid, b_start, b_end, kind in (await session.execute(q_b)).all():
            schedules[mid].busy.append(Busy(b_start, b_end, kind == BOOKING))
    return Availability(
        schedules,
        now or now_utc(),
        s.tz,
        step_min=s.slot_step_min,
        lead_min=s.min_lead_min if lead_min is None else lead_min,
    )


async def free_days(session: AsyncSession, service: Service, master_ids: Sequence[int]) -> list[date]:
    days = booking_days()
    av = await load_availability(session, master_ids, days[0], days[-1])
    return av.free_days(master_ids, days, timedelta(minutes=service.duration_min))


async def free_times(
    session: AsyncSession,
    service: Service,
    master_ids: Sequence[int],
    day: date,
    *,
    lead_min: int | None = None,
) -> dict[datetime, list[int]]:
    if day not in booking_days() and lead_min is None:
        return {}
    av = await load_availability(session, master_ids, day, day, lead_min=lead_min)
    return av.slots_any(master_ids, day, timedelta(minutes=service.duration_min))


async def masters_by_load(session: AsyncSession, master_ids: Sequence[int], day: date) -> list[int]:
    start, end = day_bounds_utc(day, day)
    q = (
        select(Booking.master_id, func.count())
        .where(
            Booking.master_id.in_(master_ids),
            Booking.kind == BOOKING,
            Booking.status == ACTIVE,
            Booking.starts_at >= start,
            Booking.starts_at < end,
        )
        .group_by(Booking.master_id)
    )
    counts = dict((await session.execute(q)).all())
    order = {mid: i for i, mid in enumerate(master_ids)}
    return sorted(master_ids, key=lambda mid: (counts.get(mid, 0), order[mid]))


async def predict_master(session: AsyncSession, service: Service, start: datetime) -> int | None:
    masters = await capable_masters(session, service.id)
    day = start.astimezone(get_settings().tz).date()
    slots = await free_times(session, service, [m.id for m in masters], day)
    free = slots.get(start, [])
    if not free:
        return None
    return (await masters_by_load(session, free, day))[0]


async def create_booking(
    session: AsyncSession,
    *,
    service: Service,
    master_id: int | None,
    start: datetime,
    client: Client,
    source: str = SRC_BOT,
    note: str = "",
    lead_min: int | None = None,
) -> Booking:
    tz = get_settings().tz
    day = start.astimezone(tz).date()
    if master_id is None:
        candidates = [m.id for m in await capable_masters(session, service.id)]
    else:
        candidates = [m.id for m in await capable_masters(session, service.id) if m.id == master_id]

    existing = await session.scalar(
        select(Booking).where(
            Booking.client_id == client.id,
            Booking.service_id == service.id,
            Booking.starts_at == start,
            Booking.status == ACTIVE,
            Booking.master_id.in_(candidates or [-1]),
        )
    )
    if existing:
        return existing

    slots = await free_times(session, service, candidates, day, lead_min=lead_min)
    free = slots.get(start.astimezone(tz), [])
    if not free:
        raise SlotTaken
    ordered = await masters_by_load(session, free, day) if master_id is None else free

    for mid in ordered:
        booking = Booking(
            kind=BOOKING,
            status=ACTIVE,
            master_id=mid,
            service_id=service.id,
            client_id=client.id,
            starts_at=start,
            ends_at=start + timedelta(minutes=service.duration_min),
            price=service.price,
            source=source,
            note=note,
        )
        try:
            async with session.begin_nested():
                session.add(booking)
            return booking
        except IntegrityError as e:
            if not is_exclusion_violation(e):
                raise
    raise SlotTaken


async def create_block(
    session: AsyncSession, *, master_id: int, start: datetime, end: datetime, note: str = ""
) -> Booking:
    block = Booking(
        kind=BLOCK,
        status=ACTIVE,
        master_id=master_id,
        starts_at=start,
        ends_at=end,
        source="admin",
        note=note,
    )
    try:
        async with session.begin_nested():
            session.add(block)
    except IntegrityError as e:
        if is_exclusion_violation(e):
            raise SlotTaken from e
        raise
    return block


def can_cancel_online(booking: Booking, now: datetime | None = None) -> bool:
    deadline = booking.starts_at - timedelta(hours=get_settings().cancel_deadline_hours)
    return (now or now_utc()) <= deadline


async def cancel_booking(
    session: AsyncSession, booking: Booking, by: str, now: datetime | None = None
) -> bool:
    if booking.status != ACTIVE:
        return False
    if by == BY_CLIENT and not can_cancel_online(booking, now):
        raise CancelNotAllowed
    booking.status = CANCELLED
    booking.cancelled_at = now or now_utc()
    booking.cancelled_by = by
    await session.flush()
    return True


async def upcoming_for_client(session: AsyncSession, client_id: int) -> Sequence[Booking]:
    q = (
        select(Booking)
        .where(
            Booking.client_id == client_id,
            Booking.kind == BOOKING,
            Booking.status == ACTIVE,
            Booking.starts_at > now_utc(),
        )
        .order_by(Booking.starts_at)
    )
    return (await session.scalars(q)).all()


async def day_agenda(session: AsyncSession, day: date, master_id: int | None = None) -> Sequence[Booking]:
    start, end = day_bounds_utc(day, day)
    q = select(Booking).where(Booking.status == ACTIVE, Booking.starts_at >= start, Booking.starts_at < end)
    if master_id is not None:
        q = q.where(Booking.master_id == master_id)
    q = q.order_by(Booking.master_id, Booking.starts_at)
    return (await session.scalars(q)).all()


async def schedule_conflicts(session: AsyncSession, master_id: int) -> list[Booking]:
    tz = get_settings().tz
    q = (
        select(Booking)
        .where(
            Booking.master_id == master_id,
            Booking.kind == BOOKING,
            Booking.status == ACTIVE,
            Booking.starts_at > now_utc(),
        )
        .order_by(Booking.starts_at)
    )
    bookings = (await session.scalars(q)).all()
    if not bookings:
        return []
    d_from = bookings[0].starts_at.astimezone(tz).date()
    d_to = bookings[-1].starts_at.astimezone(tz).date()
    av = await load_availability(session, [master_id], d_from, d_to)
    out = []
    for b in bookings:
        local = b.starts_at.astimezone(tz)
        shift = av.shift(master_id, local.date())
        end_local = b.ends_at.astimezone(tz)
        if (
            shift is None
            or local.time() < shift.start
            or end_local.time() > shift.end
            or end_local.date() != local.date()
        ):
            out.append(b)
    return out
