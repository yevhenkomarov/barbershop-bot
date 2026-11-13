from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app import texts
from app.bot import keyboards as kb
from app.bot.callbacks import Menu, My, Rem
from app.bot.ui import show
from app.core import booking as svc
from app.core.notify import notify_cancelled
from app.models import ACTIVE, BY_CLIENT, Booking, Client

router = Router(name="my")


async def _own(session: AsyncSession, booking_id: int, client: Client) -> Booking | None:
    b = await session.get(Booking, booking_id)
    return b if b is not None and b.client_id == client.id else None


async def _render_list(cb: CallbackQuery, session: AsyncSession, client: Client, prefix: str = "") -> None:
    bookings = await svc.upcoming_for_client(session, client.id)
    if not bookings:
        await show(cb, (prefix + texts.NO_UPCOMING).strip(), kb.no_bookings())
        return
    items = [(b, svc.can_cancel_online(b)) for b in bookings]
    await show(cb, prefix + texts.my_bookings(items), kb.my_bookings(items))


@router.callback_query(Menu.filter(F.a == "my"))
async def my_list(cb: CallbackQuery, session: AsyncSession, client: Client) -> None:
    await _render_list(cb, session, client)


@router.callback_query(My.filter(F.a == "ask"))
async def ask_cancel(cb: CallbackQuery, callback_data: My, session: AsyncSession, client: Client) -> None:
    b = await _own(session, callback_data.id, client)
    if b is None or b.status != ACTIVE:
        return await _render_list(cb, session, client, texts.ALREADY_CANCELLED + "\n\n")
    if not svc.can_cancel_online(b):
        await cb.answer(texts.too_late_to_cancel(), show_alert=True)
        return
    await show(cb, texts.ask_cancel(b), kb.ask_cancel(b.id))


@router.callback_query(My.filter(F.a == "no"))
async def keep(cb: CallbackQuery, session: AsyncSession, client: Client) -> None:
    await _render_list(cb, session, client)


@router.callback_query(My.filter(F.a == "yes"))
async def do_cancel(
    cb: CallbackQuery, callback_data: My, session: AsyncSession, client: Client, bot: Bot
) -> None:
    b = await _own(session, callback_data.id, client)
    if b is None:
        return await _render_list(cb, session, client)
    try:
        changed = await svc.cancel_booking(session, b, BY_CLIENT)
    except svc.CancelNotAllowed:
        await cb.answer(texts.too_late_to_cancel(), show_alert=True)
        return await _render_list(cb, session, client)
    await session.commit()
    await _render_list(
        cb, session, client, (texts.CANCELLED_OK if changed else texts.ALREADY_CANCELLED) + "\n\n"
    )
    if changed:
        await notify_cancelled(bot, session, b)


@router.callback_query(Rem.filter(F.a == "ok"))
async def reminder_confirm(
    cb: CallbackQuery, callback_data: Rem, session: AsyncSession, client: Client
) -> None:
    b = await _own(session, callback_data.id, client)
    if b is None or b.status != ACTIVE:
        await show(cb, texts.ALREADY_CANCELLED, kb.only_main())
        return
    if b.confirmed_at is None:
        b.confirmed_at = svc.now_utc()
        await session.commit()
    await show(cb, texts.reminder_24_confirmed(b), None)


@router.callback_query(Rem.filter(F.a == "cancel"))
async def reminder_cancel(
    cb: CallbackQuery, callback_data: Rem, session: AsyncSession, client: Client
) -> None:
    await ask_cancel(cb, My(a="ask", id=callback_data.id), session, client)
