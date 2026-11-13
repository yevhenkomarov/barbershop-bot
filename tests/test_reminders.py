from datetime import timedelta

from sqlalchemy import update

from app.core import booking as svc
from app.models import Booking, Client
from app.worker.reminders import process_due
from tests.conftest import tomorrow_at


class Recorder:
    def __init__(self):
        self.sent: list[tuple[str, int]] = []

    async def __call__(self, kind, booking):
        self.sent.append((kind, booking.id))


async def _book(sm, shop, start, created_ago: timedelta, client="bohdan"):
    async with sm() as s:
        b = await svc.create_booking(
            s, service=shop["beard"], master_id=shop["roman"].id, start=start, client=shop[client]
        )
        await s.commit()
        await s.execute(update(Booking).where(Booking.id == b.id).values(created_at=start - created_ago))
        await s.commit()
        return b


async def test_24h_and_2h_sent_once_each_at_right_time(sm, shop):
    start = tomorrow_at(14)
    b = await _book(sm, shop, start, created_ago=timedelta(days=3))
    rec = Recorder()
    assert await process_due(sm, rec, now=start - timedelta(hours=25)) == 0
    assert await process_due(sm, rec, now=start - timedelta(hours=24)) == 1
    for _ in range(3):
        assert await process_due(sm, rec, now=start - timedelta(hours=23)) == 0
    assert await process_due(sm, rec, now=start - timedelta(hours=2, minutes=1)) == 0
    assert await process_due(sm, rec, now=start - timedelta(hours=2)) == 1
    assert await process_due(sm, rec, now=start - timedelta(hours=1)) == 0
    assert rec.sent == [("24", b.id), ("2", b.id)]


async def test_missed_24h_after_downtime_is_sent_late_but_not_after_2h_mark(sm, shop):
    start = tomorrow_at(14)
    await _book(sm, shop, start, created_ago=timedelta(days=3))
    rec = Recorder()
    assert await process_due(sm, rec, now=start - timedelta(hours=10)) == 1
    assert rec.sent[0][0] == "24"


async def test_missed_24h_skipped_when_already_in_2h_window(sm, shop):
    start = tomorrow_at(14)
    await _book(sm, shop, start, created_ago=timedelta(days=3))
    rec = Recorder()
    assert await process_due(sm, rec, now=start - timedelta(hours=1)) == 1
    assert [k for k, _ in rec.sent] == ["2"]


async def test_late_booking_gets_only_relevant_reminders(sm, shop):
    start = tomorrow_at(14)
    await _book(sm, shop, start, created_ago=timedelta(hours=5))
    rec = Recorder()
    assert await process_due(sm, rec, now=start - timedelta(hours=4)) == 0
    assert await process_due(sm, rec, now=start - timedelta(hours=2)) == 1
    assert [k for k, _ in rec.sent] == ["2"]


async def test_cancelled_and_manual_clients_get_nothing(sm, shop):
    start = tomorrow_at(14)
    b = await _book(sm, shop, start, created_ago=timedelta(days=3))
    async with sm() as s:
        manual = Client(name="Без телеграму", phone="+380000000000")
        s.add(manual)
        await s.commit()
        shop["manual"] = manual
    await _book(sm, shop, tomorrow_at(16), created_ago=timedelta(days=3), client="manual")
    async with sm() as s:
        bb = await s.get(Booking, b.id)
        await svc.cancel_booking(s, bb, "admin")
        await s.commit()
    rec = Recorder()
    assert await process_due(sm, rec, now=start - timedelta(hours=20)) == 0


async def test_failed_send_is_retried_next_cycle(sm, shop):
    start = tomorrow_at(14)
    await _book(sm, shop, start, created_ago=timedelta(days=3))

    async def boom(kind, booking):
        raise ConnectionError("telegram down")

    try:
        await process_due(sm, boom, now=start - timedelta(hours=23))
    except ConnectionError:
        pass
    rec = Recorder()
    assert await process_due(sm, rec, now=start - timedelta(hours=22)) == 1
