import logging
from datetime import datetime, time

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove
from sqlalchemy.ext.asyncio import AsyncSession

from app import texts
from app.bot import keyboards as kb
from app.bot.callbacks import Bk, Menu
from app.bot.ui import show
from app.config import get_settings
from app.core import booking as svc
from app.core import fmt
from app.core.notify import notify_new_booking
from app.models import Client, Master, Service

log = logging.getLogger(__name__)
router = Router(name="booking")


class Flow(StatesGroup):
    contact = State()
    name = State()


async def _service(session: AsyncSession, service_id: int) -> Service | None:
    s = await session.get(Service, service_id)
    return s if s and s.is_active else None


async def _master_ids(session: AsyncSession, service: Service, master_id: int) -> list[int]:
    ids = [m.id for m in await svc.capable_masters(session, service.id)]
    if master_id:
        return [master_id] if master_id in ids else []
    return ids


def _start_dt(cb: Bk) -> datetime | None:
    try:
        day = fmt.parse_d_key(cb.d)
        return datetime.combine(day, time(int(cb.t[:2]), int(cb.t[2:])), tzinfo=get_settings().tz)
    except (ValueError, IndexError):
        return None


@router.callback_query(Menu.filter(F.a == "book"))
@router.callback_query(Bk.filter(F.st == "svc"))
async def step_service(cb: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    services = await svc.active_services(session)
    if not services:
        await show(cb, texts.NO_SERVICES.format(phone=get_settings().shop_phone), kb.only_main())
        return
    await show(cb, texts.CHOOSE_SERVICE, kb.services(services))


@router.callback_query(Bk.filter(F.st == "mst"))
async def step_master(cb: CallbackQuery, callback_data: Bk, session: AsyncSession) -> None:
    service = await _service(session, callback_data.s)
    if service is None:
        return await _restart(cb, session)
    masters = await svc.capable_masters(session, service.id)
    if not masters:
        await show(cb, texts.NO_MASTERS, kb.services(await svc.active_services(session)))
        return
    await show(cb, texts.CHOOSE_MASTER, kb.masters(service.id, masters))


@router.callback_query(Bk.filter(F.st == "date"))
async def step_date(cb: CallbackQuery, callback_data: Bk, session: AsyncSession) -> None:
    service = await _service(session, callback_data.s)
    if service is None:
        return await _restart(cb, session)
    ids = await _master_ids(session, service, callback_data.m)
    days = await svc.free_days(session, service, ids) if ids else []
    if not days:
        back = kb.masters(service.id, await svc.capable_masters(session, service.id))
        await show(cb, texts.NO_DATES.format(phone=get_settings().shop_phone), back)
        return
    page = min(callback_data.p, (len(days) - 1) // kb.DATES_PER_PAGE)
    await show(cb, texts.CHOOSE_DATE, kb.dates(callback_data, days, page))


@router.callback_query(Bk.filter(F.st == "time"))
async def step_time(cb: CallbackQuery, callback_data: Bk, session: AsyncSession) -> None:
    service = await _service(session, callback_data.s)
    if service is None:
        return await _restart(cb, session)
    try:
        day = fmt.parse_d_key(callback_data.d)
    except ValueError:
        return await _restart(cb, session)
    ids = await _master_ids(session, service, callback_data.m)
    slots = await svc.free_times(session, service, ids, day) if ids else {}
    if not slots:
        return await step_date(cb, Bk(st="date", s=callback_data.s, m=callback_data.m), session)
    master = await session.get(Master, callback_data.m) if callback_data.m else None
    await show(
        cb, texts.choose_time(day, master.name if master else None), kb.times(callback_data, list(slots))
    )


@router.callback_query(Bk.filter(F.st == "sum"))
async def step_summary(
    cb: CallbackQuery, callback_data: Bk, session: AsyncSession, client: Client, state: FSMContext
) -> None:
    await state.clear()
    if not client.phone:
        await state.set_state(Flow.contact)
        await state.update_data(bk=callback_data.pack())
        try:
            await cb.message.delete()
        except Exception:
            pass
        await cb.message.answer(texts.ASK_CONTACT, reply_markup=kb.contact_request())
        await cb.answer()
        return
    text_kb = await _summary(session, callback_data, client)
    if text_kb is None:
        await show(cb, texts.SLOT_TAKEN, kb.slot_taken(callback_data))
        return
    await show(cb, *text_kb)


async def _summary(session: AsyncSession, cbd: Bk, client: Client):
    service = await _service(session, cbd.s)
    start = _start_dt(cbd)
    if service is None or start is None:
        return None
    ids = await _master_ids(session, service, cbd.m)
    slots = await svc.free_times(session, service, ids, start.date()) if ids else {}
    if start not in slots:
        return None
    if cbd.m:
        master = await session.get(Master, cbd.m)
        predicted = False
    else:
        mid = (await svc.masters_by_load(session, slots[start], start.date()))[0]
        master = await session.get(Master, mid)
        predicted = True
    return texts.summary(service, master.name, start, client.name, predicted), kb.summary(cbd)


@router.callback_query(Bk.filter(F.st == "chg"))
async def step_change(cb: CallbackQuery, callback_data: Bk) -> None:
    await show(cb, texts.WHAT_TO_CHANGE, kb.change_menu(callback_data))


@router.callback_query(Bk.filter(F.st == "ok"))
async def step_confirm(
    cb: CallbackQuery, callback_data: Bk, session: AsyncSession, client: Client, bot: Bot
) -> None:
    service = await _service(session, callback_data.s)
    start = _start_dt(callback_data)
    if service is None or start is None:
        return await _restart(cb, session)
    try:
        booking = await svc.create_booking(
            session, service=service, master_id=callback_data.m or None, start=start, client=client
        )
        await session.commit()
    except svc.SlotTaken:
        await session.rollback()
        await show(cb, texts.SLOT_TAKEN, kb.slot_taken(callback_data))
        return
    await session.refresh(booking, ["master", "service", "client"])
    await show(cb, texts.booked(booking), kb.after_booking())
    await notify_new_booking(bot, session, booking)


async def _restart(cb: CallbackQuery, session: AsyncSession) -> None:
    services = await svc.active_services(session)
    await show(cb, f"{texts.SESSION_EXPIRED}\n\n{texts.CHOOSE_SERVICE}", kb.services(services))


@router.message(StateFilter(Flow.contact), F.contact)
async def got_contact(message: Message, session: AsyncSession, client: Client, state: FSMContext) -> None:
    contact = message.contact
    if contact.user_id and contact.user_id != message.from_user.id:
        await message.answer(texts.CONTACT_NOT_YOURS, reply_markup=kb.contact_request())
        return
    client.phone = fmt.normalize_phone(contact.phone_number)
    name = " ".join(x for x in (contact.first_name, contact.last_name) if x).strip()
    if name:
        client.name = name[:100]
    await session.commit()
    data = await state.get_data()
    await state.clear()
    await message.answer(texts.CONTACT_SAVED.format(name=client.name), reply_markup=ReplyKeyboardRemove())
    await _send_summary(message, session, client, data.get("bk"))


@router.message(StateFilter(Flow.contact), F.text == texts.BTN_BACK)
async def contact_back(message: Message, session: AsyncSession, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    await message.answer(texts.BTN_BACK + " ↩️", reply_markup=ReplyKeyboardRemove())
    cbd = Bk.unpack(data["bk"]) if data.get("bk") else None
    if cbd is None:
        await message.answer(texts.welcome(), reply_markup=kb.main_menu())
        return
    service = await _service(session, cbd.s)
    ids = await _master_ids(session, service, cbd.m) if service else []
    try:
        day = fmt.parse_d_key(cbd.d)
    except ValueError:
        day = None
    slots = await svc.free_times(session, service, ids, day) if (ids and day) else {}
    if not slots:
        await message.answer(texts.welcome(), reply_markup=kb.main_menu())
        return
    master = await session.get(Master, cbd.m) if cbd.m else None
    await message.answer(
        texts.choose_time(day, master.name if master else None), reply_markup=kb.times(cbd, list(slots))
    )


@router.message(StateFilter(Flow.contact))
async def contact_hint(message: Message) -> None:
    await message.answer(texts.CONTACT_HINT, reply_markup=kb.contact_request())


@router.callback_query(Bk.filter(F.st == "name"))
async def ask_name(cb: CallbackQuery, callback_data: Bk, state: FSMContext) -> None:
    await state.set_state(Flow.name)
    await state.update_data(bk=callback_data.pack())
    await show(cb, texts.ASK_NAME, kb.back_to_summary(callback_data))


@router.message(StateFilter(Flow.name), F.text)
async def got_name(message: Message, session: AsyncSession, client: Client, state: FSMContext) -> None:
    name = message.text.strip()
    if not (1 <= len(name) <= 60) or name.startswith("/"):
        await message.answer(texts.NAME_INVALID)
        return
    client.name = name
    await session.commit()
    data = await state.get_data()
    await state.clear()
    await _send_summary(message, session, client, data.get("bk"))


async def _send_summary(message: Message, session: AsyncSession, client: Client, packed: str | None) -> None:
    if not packed:
        await message.answer(texts.welcome(), reply_markup=kb.main_menu())
        return
    cbd = Bk.unpack(packed)
    cbd = Bk(st="sum", s=cbd.s, m=cbd.m, d=cbd.d, t=cbd.t)
    text_kb = await _summary(session, cbd, client)
    if text_kb is None:
        await message.answer(texts.SLOT_TAKEN, reply_markup=kb.slot_taken(cbd))
        return
    await message.answer(text_kb[0], reply_markup=text_kb[1])
