"""Стартові дані з Excel — необов'язково: те саме можна внести вручну в адмінці.

Файл data/shop_data.xlsx не зберігається в git; формат — data/README.md.

    python -m app.scripts.seed            # послуги, майстри, тижневий графік
    python -m app.scripts.seed --demo     # + кілька демо-записів на найближчий вільний час

Повторний запуск нічого не дублює: якщо послуги вже є — скрипт зупиняється. --force перезаписує
послуги, майстрів і тижневий графік, але НЕ чіпає записи, окремі дні й відпустки.
"""

import argparse
import asyncio
import re
import sys
from datetime import time
from pathlib import Path

from openpyxl import load_workbook
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import booking as svc
from app.db import get_sessionmaker
from app.models import SRC_ADMIN, Booking, Client, Master, Service, WeeklyShift

DEFAULT_XLSX = Path(__file__).resolve().parents[2] / "data" / "shop_data.xlsx"

TIME_RANGE = re.compile(r"(\d{1,2}):(\d{2})\s*[–—-]\s*(\d{1,2}):(\d{2})")

DEMO_NOTE = "демо-запис"
DEMO_CLIENTS = [("Богдан", "+380930001122"), ("Ярослав", "+380660005566")]


def parse_range(cell) -> tuple[time, time] | None:
    m = TIME_RANGE.search(str(cell or ""))
    if not m:
        return None
    h1, m1, h2, m2 = map(int, m.groups())
    return time(h1, m1), time(h2, m2)


def read_xlsx(path: Path) -> dict:
    wb = load_workbook(path, data_only=True)
    services = []
    for row in wb["Послуги"].iter_rows(min_row=2, values_only=True):
        if not row[0]:
            continue
        sid, name, dur, price, descr, active = row[:6]
        services.append(
            {
                "id": int(sid),
                "name": str(name).strip(),
                "duration_min": int(dur),
                "price": int(price),
                "description": str(descr or "").strip(),
                "is_active": str(active).strip().lower() == "так",
            }
        )
    masters = []
    for row in wb["Майстри"].iter_rows(min_row=2, values_only=True):
        if not row[0] or not str(row[0]).strip().isdigit():
            continue
        mid, name, tg, svc_ids, note = row[:5]
        masters.append(
            {
                "id": int(mid),
                "name": str(name).strip(),
                "tg_username": str(tg or "").strip().lstrip("@") or None,
                "service_ids": [int(x) for x in re.findall(r"\d+", str(svc_ids or ""))],
                "note": str(note or "").strip(),
            }
        )
    sheet = next(ws for ws in wb.worksheets if ws.title.startswith("Графік"))
    schedule: dict[str, dict[int, tuple[time, time] | None]] = {}
    for row in sheet.iter_rows(min_row=2, max_row=1 + len(masters), values_only=True):
        if not row[0]:
            continue
        schedule[str(row[0]).strip()] = {wd: parse_range(row[1 + wd]) for wd in range(7)}
    return {"services": services, "masters": masters, "schedule": schedule}


async def seed(path: Path, demo: bool, force: bool) -> None:
    data = read_xlsx(path)
    async with get_sessionmaker()() as s:
        if await s.scalar(select(func.count()).select_from(Service)):
            if not force:
                print("Дані вже є — нічого не роблю (використайте --force, щоб перезаписати довідники).")
                return
            await s.execute(delete(WeeklyShift))

        services: dict[int, Service] = {}
        for i, row in enumerate(data["services"], 1):
            service = await s.scalar(select(Service).where(Service.name == row["name"])) or Service()
            service.name = row["name"]
            service.short_name = row["name"].split(" (")[0]
            service.description = row["description"]
            service.duration_min = row["duration_min"]
            service.price = row["price"]
            service.is_active = row["is_active"]
            service.sort_order = i
            s.add(service)
            services[row["id"]] = service
        await s.flush()

        masters: dict[str, Master] = {}
        for i, row in enumerate(data["masters"], 1):
            m = await s.scalar(select(Master).where(Master.name == row["name"])) or Master()
            m.name = row["name"]
            m.tg_username = row["tg_username"]
            m.note = row["note"]
            m.sort_order = i
            m.services = [services[x] for x in row["service_ids"] if x in services]
            s.add(m)
            masters[row["name"]] = m
        await s.flush()

        for name, days in data["schedule"].items():
            m = masters.get(name)
            if m is None:
                continue
            for wd, rng in days.items():
                if rng:
                    s.add(WeeklyShift(master_id=m.id, weekday=wd, start_time=rng[0], end_time=rng[1]))
        await s.flush()

        added = await _demo_bookings(s) if demo else 0
        await s.commit()
    print(
        f"Готово: послуг {len(data['services'])}, майстрів {len(data['masters'])}."
        + (f" Демо-записів додано: {added}." if demo else "")
    )


async def _demo_bookings(s: AsyncSession) -> int:
    if await s.scalar(select(func.count()).select_from(Booking).where(Booking.note == DEMO_NOTE)):
        return 0
    added = 0
    for (name, phone), service in zip(DEMO_CLIENTS, await svc.active_services(s), strict=False):
        master_ids = [m.id for m in await svc.capable_masters(s, service.id)]
        days = await svc.free_days(s, service, master_ids)
        if not days:
            continue
        start = min(await svc.free_times(s, service, master_ids, days[0]))
        client = await s.scalar(select(Client).where(Client.phone == phone)) or Client(name=name, phone=phone)
        s.add(client)
        await s.flush()
        await svc.create_booking(
            s, service=service, master_id=None, start=start, client=client, source=SRC_ADMIN, note=DEMO_NOTE
        )
        added += 1
    return added


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("xlsx", nargs="?", type=Path, default=DEFAULT_XLSX)
    p.add_argument("--demo", action="store_true", help="додати кілька демо-записів на найближчий вільний час")
    p.add_argument("--force", action="store_true", help="перезаписати послуги, майстрів і тижневий графік")
    args = p.parse_args()
    if not args.xlsx.is_file():
        sys.exit(
            f"Файл {args.xlsx} не знайдено. Покладіть дані закладу в data/shop_data.xlsx (формат — data/README.md)."
        )
    asyncio.run(seed(args.xlsx, args.demo, args.force))


if __name__ == "__main__":
    main()
