import os
from datetime import UTC, date, datetime, time, timedelta

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.models import Client, Master, Service, WeeklyShift

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="session")
def database_url():
    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        yield url
        return
    from testcontainers.community.postgres import PostgresContainer

    with PostgresContainer("postgres:17-alpine", username="test", password="test", dbname="test") as pg:
        host, port = pg.get_container_host_ip(), pg.get_exposed_port(5432)
        yield f"postgresql+asyncpg://test:test@{host}:{port}/test"


@pytest.fixture(scope="session")
def migrated(database_url):
    os.environ["DATABASE_URL"] = database_url
    get_settings.cache_clear()
    cfg = Config(os.path.join(ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(ROOT, "migrations"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    return database_url


@pytest.fixture
async def engine(migrated):
    eng = create_async_engine(migrated)
    async with eng.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE bookings, clients, master_services, weekly_shifts, shift_overrides, vacations, "
                "masters, services RESTART IDENTITY CASCADE"
            )
        )
    yield eng
    await eng.dispose()


@pytest.fixture
def sm(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
async def shop(sm):
    async with sm() as s:
        haircut = Service(name="Стрижка", short_name="Стрижка", duration_min=60, price=500, sort_order=1)
        beard = Service(name="Корекція бороди", short_name="Борода", duration_min=30, price=300, sort_order=2)
        combo = Service(
            name="Стрижка й борода",
            short_name="Комбо",
            duration_min=90,
            price=750,
            sort_order=3,
        )
        denys = Master(
            name="Денис", tg_username="denys_master", sort_order=1, services=[haircut, beard, combo]
        )
        roman = Master(
            name="Роман", tg_username="roman_master", sort_order=2, services=[haircut, beard, combo]
        )
        viktor = Master(name="Віктор", tg_username="viktor_master", sort_order=3, services=[haircut])
        s.add_all([haircut, beard, combo, denys, roman, viktor])
        await s.flush()
        for m in (denys, roman, viktor):
            for wd in range(7):
                s.add(WeeklyShift(master_id=m.id, weekday=wd, start_time=time(9), end_time=time(19)))
        bohdan = Client(name="Богдан", phone="+380930001122", tg_user_id=111)
        nazar = Client(name="Назар", phone="+380990003344", tg_user_id=222)
        s.add_all([bohdan, nazar])
        await s.commit()
        return {
            "haircut": haircut, "beard": beard, "combo": combo,
            "denys": denys, "roman": roman, "viktor": viktor,
            "bohdan": bohdan, "nazar": nazar,
        }  # fmt: skip


def tomorrow_at(hh: int, mm: int = 0) -> datetime:
    tz = get_settings().tz
    d: date = datetime.now(UTC).astimezone(tz).date() + timedelta(days=1)
    return datetime.combine(d, time(hh, mm), tzinfo=tz)
