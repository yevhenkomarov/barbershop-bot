import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import texts
from app.config import get_settings
from app.models import BY_ADMIN, Booking, Client

log = logging.getLogger(__name__)


async def admin_chat_ids(session: AsyncSession) -> set[int]:
    s = get_settings()
    ids = set(s.admin_ids)
    if s.admin_usernames:
        q = select(Client.tg_user_id).where(
            func.lower(Client.tg_username).in_(s.admin_usernames), Client.tg_user_id.is_not(None)
        )
        ids.update((await session.scalars(q)).all())
    return ids


def is_admin(tg_user_id: int, username: str | None) -> bool:
    s = get_settings()
    return tg_user_id in s.admin_ids or (username or "").lower() in s.admin_usernames


async def _send(bot: Bot, chat_id: int, text: str, **kwargs) -> bool:
    try:
        await bot.send_message(chat_id, text, **kwargs)
        return True
    except TelegramAPIError as e:
        log.warning("Не вдалося надіслати повідомлення %s: %s", chat_id, e)
        return False


async def _staff_targets(session: AsyncSession, booking: Booking, include_admins: bool) -> set[int]:
    targets = set()
    if include_admins:
        targets |= await admin_chat_ids(session)
    if booking.master.tg_user_id:
        targets.add(booking.master.tg_user_id)
    return targets


async def notify_new_booking(bot: Bot | None, session: AsyncSession, booking: Booking) -> None:
    if bot is None:
        return
    by_admin = booking.source == BY_ADMIN
    for chat_id in await _staff_targets(session, booking, include_admins=not by_admin):
        await _send(bot, chat_id, texts.staff_new(booking))
    if by_admin and booking.client and booking.client.tg_user_id:
        await _send(bot, booking.client.tg_user_id, texts.booked_by_admin_for_client(booking))


async def notify_cancelled(bot: Bot | None, session: AsyncSession, booking: Booking) -> None:
    if bot is None:
        return
    by_admin = booking.cancelled_by == BY_ADMIN
    for chat_id in await _staff_targets(session, booking, include_admins=not by_admin):
        await _send(bot, chat_id, texts.staff_cancelled(booking))
    if by_admin and booking.client and booking.client.tg_user_id:
        await _send(bot, booking.client.tg_user_id, texts.cancelled_by_admin_for_client(booking))
