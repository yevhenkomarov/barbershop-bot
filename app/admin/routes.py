from datetime import date, datetime, time, timedelta
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core import booking as svc
from app.core import fmt
from app.core.notify import notify_cancelled, notify_new_booking
from app.db import get_sessionmaker
from app.models import (
    ACTIVE,
    BLOCK,
    BY_ADMIN,
    CANCELLED,
    SRC_ADMIN,
    Booking,
    Client,
    Master,
    Service,
    ShiftOverride,
    Vacation,
    WeeklyShift,
)


async def get_session():
    async with get_sessionmaker()() as session:
        yield session


def flash(request: Request, text: str, level: str = "ok") -> None:
    request.session.setdefault("flash", []).append([level, text])


def redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def parse_date(raw, default: date | None = None) -> date | None:
    try:
        return date.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return default


def parse_time(raw) -> time | None:
    try:
        return time.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None


def parse_int(raw, default: int | None = None) -> int | None:
    try:
        return int(str(raw))
    except (TypeError, ValueError):
        return default


def local_dt(d: date, t: time) -> datetime:
    return datetime.combine(d, t, tzinfo=get_settings().tz)


def build_router(templates: Jinja2Templates) -> APIRouter:
    r = APIRouter()

    def render(request: Request, name: str, ctx: dict) -> HTMLResponse:
        ctx["flashes"] = request.session.pop("flash", [])
        ctx["path"] = request.url.path
        return templates.TemplateResponse(request, name, ctx)

    async def all_masters(session: AsyncSession) -> list[Master]:
        return list((await session.scalars(select(Master).order_by(Master.sort_order, Master.id))).all())

    async def all_services(session: AsyncSession) -> list[Service]:
        return list((await session.scalars(select(Service).order_by(Service.sort_order, Service.id))).all())

    @r.get("/")
    async def index():
        return redirect("/bookings")

    @r.get("/bookings", response_class=HTMLResponse)
    async def bookings(request: Request, session: AsyncSession = Depends(get_session)):
        q = request.query_params
        today = svc.local_now().date()
        d_from = parse_date(q.get("date_from"), today)
        d_to = parse_date(q.get("date_to"), d_from)
        if d_to < d_from:
            d_to = d_from
        master_id = parse_int(q.get("master_id"))
        status = q.get("status", "active")
        start, end = svc.day_bounds_utc(d_from, d_to)
        stmt = select(Booking).where(Booking.starts_at >= start, Booking.starts_at < end)
        if master_id:
            stmt = stmt.where(Booking.master_id == master_id)
        if status in (ACTIVE, CANCELLED):
            stmt = stmt.where(Booking.status == status)
        items = (await session.scalars(stmt.order_by(Booking.starts_at, Booking.master_id))).all()
        total = sum(b.price or 0 for b in items if b.status == ACTIVE and b.kind != BLOCK)
        return render(
            request,
            "bookings.html",
            {
                "items": items,
                "masters": await all_masters(session),
                "f": {"date_from": d_from, "date_to": d_to, "master_id": master_id, "status": status},
                "today": today,
                "timedelta": timedelta,
                "total": total,
                "back": str(request.url.path) + ("?" + str(request.url.query) if request.url.query else ""),
            },
        )

    @r.post("/bookings/{booking_id}/cancel")
    async def cancel(booking_id: int, request: Request, session: AsyncSession = Depends(get_session)):
        form = await request.form()
        back = str(form.get("back") or "/bookings")
        b = await session.get(Booking, booking_id)
        if b is None:
            flash(request, "Запис не знайдено.", "err")
            return redirect(back)
        changed = await svc.cancel_booking(session, b, BY_ADMIN)
        await session.commit()
        if changed and b.kind != BLOCK:
            await notify_cancelled(request.app.state.bot, session, b)
            flash(
                request,
                f"Запис {fmt.d_short(b.starts_at)} {fmt.hm(b.starts_at)} ({b.client.name}) скасовано.",
            )
        elif changed:
            flash(request, "Перерву видалено.")
        return redirect(back if back.startswith("/") else "/bookings")

    @r.get("/bookings/new", response_class=HTMLResponse)
    async def new_booking(request: Request, session: AsyncSession = Depends(get_session)):
        q = request.query_params
        services = [s for s in await all_services(session) if s.is_active]
        service = await session.get(Service, parse_int(q.get("service_id"), 0) or 0)
        master_id = parse_int(q.get("master_id"), 0) or 0
        day = parse_date(q.get("day"))
        masters = list(await svc.capable_masters(session, service.id)) if service else []
        slots: dict = {}
        if service and day:
            ids = [m.id for m in masters if not master_id or m.id == master_id]
            slots = await svc.free_times(session, service, ids, day, lead_min=0) if ids else {}
        return render(
            request,
            "booking_new.html",
            {
                "services": services,
                "service": service,
                "masters": masters,
                "master_id": master_id,
                "day": day,
                "slots": slots,
                "today": svc.local_now().date(),
                "form": request.session.pop("form", {}),
            },
        )

    @r.post("/bookings/new")
    async def create_booking(request: Request, session: AsyncSession = Depends(get_session)):
        form = await request.form()
        service = await session.get(Service, parse_int(form.get("service_id"), 0) or 0)
        master_id = parse_int(form.get("master_id"), 0) or None
        day = parse_date(form.get("day"))
        t = parse_time(form.get("time"))
        name = str(form.get("name", "")).strip()[:100]
        phone = fmt.normalize_phone(str(form.get("phone", "")))
        note = str(form.get("note", "")).strip()
        back = "/bookings/new?" + urlencode(
            {
                "service_id": form.get("service_id", ""),
                "master_id": form.get("master_id", ""),
                "day": form.get("day", ""),
            }
        )
        request.session["form"] = {"name": name, "phone": form.get("phone", ""), "note": note}
        if not (service and day and t):
            flash(request, "Оберіть послугу, дату й час.", "err")
            return redirect(back)
        if not name or len(phone) < 11:
            flash(request, "Вкажіть імʼя та телефон клієнта.", "err")
            return redirect(back)
        client = await session.scalar(
            select(Client).where(Client.phone == phone).order_by(Client.tg_user_id.is_(None))
        )
        if client is None:
            client = Client(name=name, phone=phone)
            session.add(client)
            await session.flush()
        elif client.tg_user_id is None:
            client.name = name
        try:
            b = await svc.create_booking(
                session,
                service=service,
                master_id=master_id,
                start=local_dt(day, t),
                client=client,
                source=SRC_ADMIN,
                note=note,
                lead_min=0,
            )
            await session.commit()
        except svc.SlotTaken:
            await session.rollback()
            flash(request, "Цей час уже недоступний або не вміщується в зміну. Оберіть інший.", "err")
            return redirect(back)
        request.session.pop("form", None)
        await session.refresh(b, ["master", "service", "client"])
        await notify_new_booking(request.app.state.bot, session, b)
        flash(
            request,
            f"Записано: {fmt.d_short(b.starts_at)} {fmt.hm(b.starts_at)}, {b.service.short_name}, {b.master.name}, {b.client.name}.",
        )
        return redirect(f"/bookings?date_from={day.isoformat()}")

    @r.get("/blocks/new", response_class=HTMLResponse)
    async def new_block(request: Request, session: AsyncSession = Depends(get_session)):
        q = request.query_params
        return render(
            request,
            "block_new.html",
            {
                "masters": [m for m in await all_masters(session) if m.is_active],
                "master_id": parse_int(q.get("master_id"), 0),
                "day": parse_date(q.get("day"), svc.local_now().date()),
            },
        )

    @r.post("/blocks/new")
    async def create_block(request: Request, session: AsyncSession = Depends(get_session)):
        form = await request.form()
        master_id = parse_int(form.get("master_id"))
        day = parse_date(form.get("day"))
        t1, t2 = parse_time(form.get("start")), parse_time(form.get("end"))
        if not (master_id and day and t1 and t2) or t2 <= t1:
            flash(request, "Перевірте майстра, дату і час (кінець має бути пізніше за початок).", "err")
            return redirect("/blocks/new")
        try:
            await svc.create_block(
                session,
                master_id=master_id,
                start=local_dt(day, t1),
                end=local_dt(day, t2),
                note=str(form.get("note", "")),
            )
            await session.commit()
        except svc.SlotTaken:
            await session.rollback()
            flash(request, "На цей час уже є запис або перерва.", "err")
            return redirect(f"/blocks/new?master_id={master_id}&day={day.isoformat()}")
        flash(request, "Час заблоковано — у боті він більше не доступний.")
        return redirect(f"/bookings?date_from={day.isoformat()}&master_id={master_id}")

    @r.get("/services", response_class=HTMLResponse)
    async def services(request: Request, session: AsyncSession = Depends(get_session)):
        return render(request, "services.html", {"items": await all_services(session)})

    @r.get("/services/{service_id}", response_class=HTMLResponse)
    @r.get("/services/new", response_class=HTMLResponse)
    async def service_form(
        request: Request, service_id: int | None = None, session: AsyncSession = Depends(get_session)
    ):
        item = await session.get(Service, service_id) if service_id else None
        return render(request, "service_form.html", {"item": item})

    @r.post("/services/{service_id}")
    @r.post("/services/new")
    async def service_save(
        request: Request, service_id: int | None = None, session: AsyncSession = Depends(get_session)
    ):
        form = await request.form()
        item = await session.get(Service, service_id) if service_id else Service()
        name = str(form.get("name", "")).strip()
        duration = parse_int(form.get("duration_min"))
        price = parse_int(form.get("price"))
        if not name or not duration or duration < 5 or duration > 480 or price is None or price < 0:
            flash(request, "Заповніть назву, тривалість (5–480 хв) і ціну.", "err")
            return redirect(request.url.path)
        item.name = name[:100]
        item.short_name = (str(form.get("short_name", "")).strip() or name)[:40]
        item.description = str(form.get("description", "")).strip()
        item.duration_min = duration
        item.price = price
        item.sort_order = parse_int(form.get("sort_order"), 0)
        item.is_active = form.get("is_active") == "on"
        if not service_id:
            session.add(item)
        await session.commit()
        flash(request, f"Послугу «{item.name}» збережено.")
        return redirect("/services")

    @r.get("/masters", response_class=HTMLResponse)
    async def masters(request: Request, session: AsyncSession = Depends(get_session)):
        return render(request, "masters.html", {"items": await all_masters(session)})

    @r.get("/masters/{master_id}", response_class=HTMLResponse)
    @r.get("/masters/new", response_class=HTMLResponse)
    async def master_page(
        request: Request, master_id: int | None = None, session: AsyncSession = Depends(get_session)
    ):
        item = await session.get(Master, master_id) if master_id else None
        ctx = {"item": item, "services": await all_services(session), "weekdays": fmt.WD_NOM}
        if item:
            today = svc.local_now().date()
            weekly = {
                w.weekday: w
                for w in await session.scalars(select(WeeklyShift).where(WeeklyShift.master_id == item.id))
            }
            ctx["weekly"] = weekly
            ctx["overrides"] = (
                await session.scalars(
                    select(ShiftOverride)
                    .where(ShiftOverride.master_id == item.id, ShiftOverride.day >= today)
                    .order_by(ShiftOverride.day)
                )
            ).all()
            ctx["vacations"] = (
                await session.scalars(
                    select(Vacation)
                    .where(Vacation.master_id == item.id, Vacation.date_to >= today)
                    .order_by(Vacation.date_from)
                )
            ).all()
            ctx["conflicts"] = await svc.schedule_conflicts(session, item.id)
            ctx["today"] = today
        return render(request, "master_form.html", ctx)

    @r.post("/masters/{master_id}")
    @r.post("/masters/new")
    async def master_save(
        request: Request, master_id: int | None = None, session: AsyncSession = Depends(get_session)
    ):
        form = await request.form()
        item = await session.get(Master, master_id) if master_id else Master()
        name = str(form.get("name", "")).strip()
        if not name:
            flash(request, "Вкажіть імʼя майстра.", "err")
            return redirect(request.url.path)
        username = str(form.get("tg_username", "")).strip().lstrip("@").removeprefix("https://t.me/") or None
        if (username or "").lower() != (item.tg_username or "").lower():
            item.tg_user_id = None
        item.name = name[:60]
        item.tg_username = username
        item.note = str(form.get("note", "")).strip()
        item.sort_order = parse_int(form.get("sort_order"), 0)
        item.is_active = form.get("is_active") == "on"
        chosen = {int(x) for x in form.getlist("services") if str(x).isdigit()}
        item.services = [s for s in await all_services(session) if s.id in chosen]
        if not master_id:
            session.add(item)
        await session.commit()
        flash(request, f"Майстра «{item.name}» збережено.")
        return redirect(f"/masters/{item.id}")

    @r.post("/masters/{master_id}/weekly")
    async def weekly_save(master_id: int, request: Request, session: AsyncSession = Depends(get_session)):
        form = await request.form()
        rows = []
        for wd in range(7):
            if form.get(f"work_{wd}") != "on":
                continue
            t1, t2 = parse_time(form.get(f"start_{wd}")), parse_time(form.get(f"end_{wd}"))
            if not t1 or not t2 or t2 <= t1:
                flash(
                    request,
                    f"{fmt.WD_NOM[wd].capitalize()}: кінець зміни має бути пізніше за початок.",
                    "err",
                )
                return redirect(f"/masters/{master_id}")
            rows.append(WeeklyShift(master_id=master_id, weekday=wd, start_time=t1, end_time=t2))
        await session.execute(delete(WeeklyShift).where(WeeklyShift.master_id == master_id))
        session.add_all(rows)
        await session.commit()
        flash(request, "Тижневий графік збережено — бот уже показує новий вільний час.")
        return redirect(f"/masters/{master_id}")

    @r.post("/masters/{master_id}/overrides")
    async def override_add(master_id: int, request: Request, session: AsyncSession = Depends(get_session)):
        form = await request.form()
        day = parse_date(form.get("day"))
        off = form.get("kind") == "off"
        t1, t2 = parse_time(form.get("start")), parse_time(form.get("end"))
        if not day or (not off and (not t1 or not t2 or t2 <= t1)):
            flash(request, "Вкажіть дату та години (або позначте вихідний).", "err")
            return redirect(f"/masters/{master_id}")
        await session.execute(
            delete(ShiftOverride).where(ShiftOverride.master_id == master_id, ShiftOverride.day == day)
        )
        session.add(
            ShiftOverride(
                master_id=master_id,
                day=day,
                start_time=None if off else t1,
                end_time=None if off else t2,
                note=str(form.get("note", "")).strip(),
            )
        )
        await session.commit()
        flash(request, f"{fmt.d_short(day)}: {'вихідний' if off else f'{t1:%H:%M}–{t2:%H:%M}'}.")
        return redirect(f"/masters/{master_id}")

    @r.post("/overrides/{override_id}/delete")
    async def override_delete(
        override_id: int, request: Request, session: AsyncSession = Depends(get_session)
    ):
        ov = await session.get(ShiftOverride, override_id)
        if ov:
            await session.delete(ov)
            await session.commit()
            flash(request, "Виняток видалено.")
            return redirect(f"/masters/{ov.master_id}")
        return redirect("/masters")

    @r.post("/masters/{master_id}/vacations")
    async def vacation_add(master_id: int, request: Request, session: AsyncSession = Depends(get_session)):
        form = await request.form()
        d1, d2 = parse_date(form.get("date_from")), parse_date(form.get("date_to"))
        if not d1 or not d2 or d2 < d1:
            flash(request, "Перевірте дати відпустки.", "err")
            return redirect(f"/masters/{master_id}")
        session.add(
            Vacation(master_id=master_id, date_from=d1, date_to=d2, note=str(form.get("note", "")).strip())
        )
        await session.commit()
        flash(request, f"Відпустку {d1:%d.%m}–{d2:%d.%m} додано.")
        return redirect(f"/masters/{master_id}")

    @r.post("/vacations/{vacation_id}/delete")
    async def vacation_delete(
        vacation_id: int, request: Request, session: AsyncSession = Depends(get_session)
    ):
        v = await session.get(Vacation, vacation_id)
        if v:
            await session.delete(v)
            await session.commit()
            flash(request, "Відпустку видалено.")
            return redirect(f"/masters/{v.master_id}")
        return redirect("/masters")

    return r
