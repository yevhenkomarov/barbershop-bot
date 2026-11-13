import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core import booking as svc
from app.models import ACTIVE, BY_ADMIN, BY_CLIENT, CANCELLED, Booking, Master, ShiftOverride, Vacation
from tests.conftest import tomorrow_at


async def test_double_booking_impossible_under_concurrency(sm, shop):
    start = tomorrow_at(14, 30)

    async def attempt(client):
        async with sm() as s:
            service = await s.get(type(shop["combo"]), shop["combo"].id)
            c = await s.get(type(client), client.id)
            try:
                await svc.create_booking(
                    s, service=service, master_id=shop["roman"].id, start=start, client=c
                )
                await s.commit()
                return "ok"
            except svc.SlotTaken:
                await s.rollback()
                return "taken"

    results = await asyncio.gather(*(attempt(c) for c in [shop["bohdan"], shop["nazar"]] * 5))
    assert results.count("ok") == 1
    async with sm() as s:
        n = len((await s.scalars(select(Booking).where(Booking.status == ACTIVE))).all())
    assert n == 1


async def test_overlapping_insert_rejected_by_db_constraint(sm, shop):
    from sqlalchemy.exc import IntegrityError

    start = tomorrow_at(14, 30)
    async with sm() as s:
        s.add(Booking(master_id=shop["roman"].id, service_id=shop["combo"].id, client_id=shop["bohdan"].id,
                      starts_at=start, ends_at=start + timedelta(minutes=90)))  # fmt: skip
        await s.commit()
        s.add(Booking(master_id=shop["roman"].id, service_id=shop["haircut"].id, client_id=shop["nazar"].id,
                      starts_at=start + timedelta(minutes=30), ends_at=start + timedelta(minutes=90)))  # fmt: skip
        with pytest.raises(IntegrityError) as e:
            await s.commit()
        assert svc.is_exclusion_violation(e.value)


async def test_cancel_frees_slot(sm, shop):
    start = tomorrow_at(12)
    async with sm() as s:
        b = await svc.create_booking(
            s, service=shop["haircut"], master_id=shop["denys"].id, start=start, client=shop["bohdan"]
        )
        await s.commit()
        slots = await svc.free_times(s, shop["haircut"], [shop["denys"].id], start.date())
        assert start not in slots
        await svc.cancel_booking(s, b, BY_CLIENT)
        await s.commit()
        slots = await svc.free_times(s, shop["haircut"], [shop["denys"].id], start.date())
        assert start in slots
        await svc.create_booking(
            s, service=shop["haircut"], master_id=shop["denys"].id, start=start, client=shop["nazar"]
        )
        await s.commit()


async def test_combo_not_offered_if_not_fits_before_next_booking(sm, shop):
    async with sm() as s:
        await svc.create_booking(
            s,
            service=shop["haircut"],
            master_id=shop["roman"].id,
            start=tomorrow_at(12),
            client=shop["bohdan"],
        )
        await s.commit()
        slots = await svc.free_times(s, shop["combo"], [shop["roman"].id], tomorrow_at(12).date())
        assert tomorrow_at(11) not in slots
        assert tomorrow_at(10, 30) in slots
        assert tomorrow_at(17, 30) in slots and tomorrow_at(18) not in slots


async def test_any_master_assigns_least_loaded_and_skips_incapable(sm, shop):
    async with sm() as s:
        await svc.create_booking(
            s, service=shop["beard"], master_id=shop["denys"].id, start=tomorrow_at(10), client=shop["nazar"]
        )
        await s.commit()
        b = await svc.create_booking(
            s, service=shop["beard"], master_id=None, start=tomorrow_at(15), client=shop["bohdan"]
        )
        await s.commit()
        assert b.master_id == shop["roman"].id
        assert await svc.predict_master(s, shop["beard"], tomorrow_at(16)) in {
            shop["denys"].id,
            shop["roman"].id,
        }


async def test_any_master_falls_back_when_first_is_taken(sm, shop):
    async with sm() as s:
        await svc.create_booking(
            s,
            service=shop["haircut"],
            master_id=shop["denys"].id,
            start=tomorrow_at(15),
            client=shop["nazar"],
        )
        await svc.create_booking(
            s,
            service=shop["haircut"],
            master_id=shop["roman"].id,
            start=tomorrow_at(15),
            client=shop["nazar"],
        )
        await s.commit()
        b = await svc.create_booking(
            s, service=shop["haircut"], master_id=None, start=tomorrow_at(15), client=shop["bohdan"]
        )
        assert b.master_id == shop["viktor"].id
        await s.commit()
        with pytest.raises(svc.SlotTaken):
            await svc.create_booking(
                s,
                service=shop["haircut"],
                master_id=None,
                start=tomorrow_at(15),
                client=shop["bohdan"].__class__(id=999),
            )


async def test_master_cannot_be_booked_for_service_he_does_not_do(sm, shop):
    async with sm() as s:
        with pytest.raises(svc.SlotTaken):
            await svc.create_booking(
                s,
                service=shop["beard"],
                master_id=shop["viktor"].id,
                start=tomorrow_at(12),
                client=shop["bohdan"],
            )


async def test_double_click_confirm_is_idempotent(sm, shop):
    async with sm() as s:
        a = await svc.create_booking(
            s, service=shop["beard"], master_id=shop["roman"].id, start=tomorrow_at(12), client=shop["bohdan"]
        )
        await s.commit()
        b = await svc.create_booking(
            s, service=shop["beard"], master_id=shop["roman"].id, start=tomorrow_at(12), client=shop["bohdan"]
        )
        assert a.id == b.id


async def test_schedule_changes_apply_immediately(sm, shop):
    day = tomorrow_at(10).date()
    ids = [shop["denys"].id]
    async with sm() as s:
        assert day in await svc.free_days(s, shop["haircut"], ids)
        s.add(ShiftOverride(master_id=shop["denys"].id, day=day, start_time=None, end_time=None))
        await s.commit()
        assert day not in await svc.free_days(s, shop["haircut"], ids)
        await s.execute(ShiftOverride.__table__.delete())
        s.add(Vacation(master_id=shop["denys"].id, date_from=day, date_to=day + timedelta(days=2)))
        await s.commit()
        days = await svc.free_days(s, shop["haircut"], ids)
        assert day not in days and day + timedelta(days=3) in days


async def test_blocks_are_busy_and_conflict_with_bookings(sm, shop):
    async with sm() as s:
        await svc.create_block(
            s, master_id=shop["roman"].id, start=tomorrow_at(13), end=tomorrow_at(14), note="обід"
        )
        await s.commit()
        slots = await svc.free_times(s, shop["haircut"], [shop["roman"].id], tomorrow_at(13).date())
        assert tomorrow_at(13) not in slots and tomorrow_at(12, 30) not in slots and tomorrow_at(14) in slots
        with pytest.raises(svc.SlotTaken):
            await svc.create_block(
                s, master_id=shop["roman"].id, start=tomorrow_at(13, 30), end=tomorrow_at(14, 30)
            )


async def test_client_cancel_deadline_3h(sm, shop):
    async with sm() as s:
        b = await svc.create_booking(
            s, service=shop["beard"], master_id=shop["roman"].id, start=tomorrow_at(12), client=shop["bohdan"]
        )
        await s.commit()
        too_late = b.starts_at - timedelta(hours=2, minutes=59)
        with pytest.raises(svc.CancelNotAllowed):
            await svc.cancel_booking(s, b, BY_CLIENT, now=too_late)
        assert await svc.cancel_booking(s, b, BY_ADMIN, now=too_late)
        assert b.status == CANCELLED


async def test_schedule_conflicts_detected(sm, shop):
    async with sm() as s:
        b = await svc.create_booking(
            s,
            service=shop["haircut"],
            master_id=shop["denys"].id,
            start=tomorrow_at(18),
            client=shop["bohdan"],
        )
        await s.commit()
        assert await svc.schedule_conflicts(s, shop["denys"].id) == []
        s.add(ShiftOverride(master_id=shop["denys"].id, day=b.starts_at.date(), start_time=tomorrow_at(10).time(),
                            end_time=tomorrow_at(16).time()))  # fmt: skip
        await s.commit()
        conflicts = await svc.schedule_conflicts(s, shop["denys"].id)
        assert [c.id for c in conflicts] == [b.id]
        assert (await s.get(Master, shop["denys"].id)).name == "Денис"
