from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.core.availability import Availability, Busy, MasterSchedule, Shift, day_slots, resolve_shift

KYIV = ZoneInfo("Europe/Kyiv")
HAIRCUT = timedelta(minutes=60)
BEARD = timedelta(minutes=30)
COMBO = timedelta(minutes=90)
NOW = datetime(2027, 2, 2, 9, 0, tzinfo=KYIV)


def k(d: date, hh: int, mm: int = 0) -> datetime:
    return datetime.combine(d, time(hh, mm), tzinfo=KYIV)


def hm(slots: list[datetime]) -> list[str]:
    return [s.strftime("%H:%M") for s in slots]


def slots(d, shift, busy, dur, now=NOW):
    return hm(day_slots(d, shift, busy, dur, now, KYIV))


TUE = date(2027, 2, 9)
FRI = date(2027, 2, 12)
SUN = date(2027, 2, 14)


def test_booking_blocks_overlapping_start_times():
    busy = [Busy(k(TUE, 13), k(TUE, 14, 30))]
    s = slots(TUE, Shift(time(10), time(19)), busy, HAIRCUT)
    assert not {"12:30", "13:00", "13:30", "14:00"} & set(s)
    assert "12:00" in s and "14:30" in s
    assert "12:30" in slots(TUE, Shift(time(10), time(19)), busy, BEARD)


def test_service_must_end_before_shift_end():
    s = slots(TUE, Shift(time(10), time(17)), [], HAIRCUT)
    assert s[-1] == "16:00"


def test_short_service_fits_at_end_of_day_long_one_does_not():
    busy = [Busy(k(FRI, 17, 30), k(FRI, 18))]
    shift = Shift(time(11), time(19))
    assert "18:30" in slots(FRI, shift, busy, BEARD)
    combo = slots(FRI, shift, busy, COMBO)
    assert "18:00" not in combo and combo[-1] == "16:00"


def test_step_is_30_minutes_and_starts_at_shift():
    assert slots(TUE, Shift(time(10), time(12)), [], BEARD) == ["10:00", "10:30", "11:00", "11:30"]


def test_today_only_future_with_30_min_lead():
    now = k(TUE, 12, 10)
    s = slots(TUE, Shift(time(10), time(20)), [], BEARD, now=now)
    assert s[0] == "13:00"
    now = k(TUE, 12, 0)
    assert slots(TUE, Shift(time(10), time(20)), [], BEARD, now=now)[0] == "12:30"


def test_past_day_has_no_slots():
    assert slots(TUE, Shift(time(10), time(20)), [], BEARD, now=k(TUE, 21)) == []


def test_day_off():
    assert slots(TUE, None, [], BEARD) == []


def test_dst_switch_day_slots_and_durations():
    d = date(2026, 10, 25)
    s = day_slots(d, Shift(time(10), time(20)), [], COMBO, datetime(2026, 10, 20, tzinfo=UTC), KYIV)
    assert hm(s)[0] == "10:00" and hm(s)[-1] == "18:30"
    assert s[0].utcoffset() == timedelta(hours=2)
    d = date(2026, 3, 29)
    s = day_slots(d, Shift(time(10), time(20)), [], COMBO, datetime(2026, 3, 20, tzinfo=UTC), KYIV)
    assert hm(s)[-1] == "18:30" and s[0].utcoffset() == timedelta(hours=3)


def test_resolve_shift_priority():
    sched = MasterSchedule(
        weekly={6: Shift(time(10), time(20))},
        overrides={SUN: Shift(time(10), time(15)), date(2027, 2, 21): None},
        vacations=[(date(2027, 2, 22), date(2027, 2, 28))],
    )
    sched.weekly[0] = Shift(time(10), time(20))
    assert resolve_shift(SUN, sched) == Shift(time(10), time(15))
    assert resolve_shift(date(2027, 2, 21), sched) is None
    assert resolve_shift(date(2027, 2, 22), sched) is None
    assert resolve_shift(date(2027, 3, 1), sched) == Shift(time(10), time(20))


def test_any_master_union_and_free_days():
    a = MasterSchedule(weekly={1: Shift(time(10), time(11))})
    b = MasterSchedule(weekly={1: Shift(time(10), time(11))}, busy=[Busy(k(TUE, 10), k(TUE, 10, 30))])
    av = Availability({1: a, 2: b}, NOW, KYIV)
    res = av.slots_any([1, 2], TUE, BEARD)
    assert {t.strftime("%H:%M"): m for t, m in res.items()} == {"10:00": [1], "10:30": [1, 2]}
    days = [TUE + timedelta(days=i) for i in range(7)]
    assert av.free_days([1, 2], days, BEARD) == [TUE]
    assert av.busy_count(2, TUE) == 1 and av.busy_count(1, TUE) == 0
