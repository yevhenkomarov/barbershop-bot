from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Shift:
    start: time
    end: time


@dataclass(frozen=True)
class Busy:
    start: datetime
    end: datetime
    is_booking: bool = True


@dataclass
class MasterSchedule:
    weekly: dict[int, Shift] = field(default_factory=dict)
    overrides: dict[date, Shift | None] = field(default_factory=dict)
    vacations: list[tuple[date, date]] = field(default_factory=list)
    busy: list[Busy] = field(default_factory=list)


def resolve_shift(day: date, sched: MasterSchedule) -> Shift | None:
    for d_from, d_to in sched.vacations:
        if d_from <= day <= d_to:
            return None
    if day in sched.overrides:
        return sched.overrides[day]
    return sched.weekly.get(day.weekday())


def day_slots(
    day: date,
    shift: Shift | None,
    busy: Iterable[Busy],
    duration: timedelta,
    now: datetime,
    tz: ZoneInfo,
    *,
    step_min: int = 30,
    lead_min: int = 30,
) -> list[datetime]:
    if shift is None or duration <= timedelta(0):
        return []
    shift_end_utc = datetime.combine(day, shift.end, tzinfo=tz).astimezone(UTC)
    earliest = now.astimezone(UTC) + timedelta(minutes=lead_min)
    busy_utc = [(b.start.astimezone(UTC), b.end.astimezone(UTC)) for b in busy]

    start_min = shift.start.hour * 60 + shift.start.minute
    first = -(-start_min // step_min) * step_min
    end_min = shift.end.hour * 60 + shift.end.minute

    result: list[datetime] = []
    for m in range(first, end_min, step_min):
        local = datetime.combine(day, time(m // 60, m % 60), tzinfo=tz)
        s = local.astimezone(UTC)
        e = s + duration
        if e > shift_end_utc or s < earliest:
            continue
        if any(s < b_end and e > b_start for b_start, b_end in busy_utc):
            continue
        result.append(local)
    return result


class Availability:
    def __init__(
        self,
        schedules: dict[int, MasterSchedule],
        now: datetime,
        tz: ZoneInfo,
        *,
        step_min: int = 30,
        lead_min: int = 30,
    ):
        self.schedules = schedules
        self.now = now
        self.tz = tz
        self.step_min = step_min
        self.lead_min = lead_min

    def shift(self, master_id: int, day: date) -> Shift | None:
        sched = self.schedules.get(master_id)
        return resolve_shift(day, sched) if sched else None

    def slots(self, master_id: int, day: date, duration: timedelta) -> list[datetime]:
        sched = self.schedules.get(master_id)
        if sched is None:
            return []
        return day_slots(
            day,
            resolve_shift(day, sched),
            sched.busy,
            duration,
            self.now,
            self.tz,
            step_min=self.step_min,
            lead_min=self.lead_min,
        )

    def slots_any(
        self, master_ids: Iterable[int], day: date, duration: timedelta
    ) -> dict[datetime, list[int]]:
        out: dict[datetime, list[int]] = {}
        for mid in master_ids:
            for s in self.slots(mid, day, duration):
                out.setdefault(s, []).append(mid)
        return dict(sorted(out.items()))

    def free_days(self, master_ids: Iterable[int], days: Iterable[date], duration: timedelta) -> list[date]:
        ids = list(master_ids)
        return [d for d in days if any(self.slots(mid, d, duration) for mid in ids)]

    def busy_count(self, master_id: int, day: date) -> int:
        sched = self.schedules.get(master_id)
        if sched is None:
            return 0
        return sum(1 for b in sched.busy if b.is_booking and b.start.astimezone(self.tz).date() == day)
