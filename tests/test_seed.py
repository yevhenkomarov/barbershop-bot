from datetime import date

from openpyxl import Workbook
from sqlalchemy import func, select

from app.models import Booking, Master, Service, Vacation, WeeklyShift
from app.scripts import seed as seed_mod


def make_xlsx(path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Послуги"
    ws.append(["ID", "Назва", "Хвилин", "Ціна", "Опис", "У боті"])
    ws.append([1, "Стрижка", 60, 500, "Класична", "так"])
    ws.append([2, "Борода", 30, 300, None, "так"])
    ws.append([3, "Гоління", 30, 300, None, "ні"])
    ws = wb.create_sheet("Майстри")
    ws.append(["ID", "Імʼя", "Telegram", "Послуги (ID)", "Примітка"])
    ws.append([1, "Марко", "@marko_master", "1, 2", "Старший"])
    ws.append([2, "Ігор", None, "1", None])
    ws.append([None, "Адміністратор:", "@shop_admin", None, "рядок без ID пропускається"])
    ws = wb.create_sheet("Графік на тиждень")
    ws.append(["Імʼя", "Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Нд"])
    ws.append(["Марко", *["09:00–19:00"] * 7])
    ws.append(
        ["Ігор", "11:00-19:00", "вихідний", "11:00–19:00", "11:00–19:00", "11:00–19:00", None, "вихідний"]
    )
    wb.save(path)


async def test_seed_from_xlsx_then_force_keeps_admin_data(sm, tmp_path, monkeypatch):
    path = tmp_path / "shop.xlsx"
    make_xlsx(path)
    monkeypatch.setattr(seed_mod, "get_sessionmaker", lambda: sm)

    await seed_mod.seed(path, demo=True, force=False)
    async with sm() as s:
        services = (await s.scalars(select(Service).order_by(Service.sort_order))).all()
        assert [(x.name, x.is_active) for x in services] == [
            ("Стрижка", True),
            ("Борода", True),
            ("Гоління", False),
        ]
        masters = {m.name: m for m in await s.scalars(select(Master))}
        assert set(masters) == {"Марко", "Ігор"}
        assert masters["Марко"].tg_username == "marko_master"
        assert masters["Ігор"].tg_username is None
        assert [x.name for x in masters["Марко"].services] == ["Стрижка", "Борода"]
        ihor_days = await s.scalars(
            select(WeeklyShift.weekday).where(WeeklyShift.master_id == masters["Ігор"].id)
        )
        assert sorted(ihor_days) == [0, 2, 3, 4]
        demo = (await s.scalars(select(Booking).where(Booking.note == seed_mod.DEMO_NOTE))).all()
        assert len(demo) == 2
        s.add(Vacation(master_id=masters["Ігор"].id, date_from=date(2030, 1, 1), date_to=date(2030, 1, 7)))
        await s.commit()

    await seed_mod.seed(path, demo=True, force=True)
    async with sm() as s:
        assert await s.scalar(select(func.count()).select_from(Service)) == 3
        assert await s.scalar(select(func.count()).select_from(Master)) == 2
        assert await s.scalar(select(func.count()).select_from(WeeklyShift)) == 7 + 4
        assert await s.scalar(select(func.count()).select_from(Booking)) == 2
        assert await s.scalar(select(func.count()).select_from(Vacation)) == 1
