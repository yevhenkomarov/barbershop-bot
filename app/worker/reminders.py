import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramNotFound
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app import texts
from app.bot import keyboards as kb
from app.core.booking import now_utc
from app.models import ACTIVE, BOOKING, Booking, Client

log = logging.getLogger(__name__)

H24 = timedelta(hours=24)
H2 = timedelta(hours=2)

Sender = Callable[[str, Booking], Awaitable[None]]


def _due_query(kind: str, now: datetime):
    q = (
        select(Booking)
        .join(Client, Client.id == Booking.client_id)
        .where(Booking.kind == BOOKING, Booking.status == ACTIVE, Client.tg_user_id.is_not(None))
    )
    if kind == "24":
        q = q.where(
            Booking.remind_24_sent_at.is_(None),
            Booking.starts_at <= now + H24,
            Booking.starts_at > now + H2,
            Booking.created_at <= Booking.starts_at - H24,
        )
    else:
        q = q.where(
            Booking.remind_2_sent_at.is_(None),
            Booking.starts_at <= now + H2,
            Booking.starts_at > now,
            Booking.created_at <= Booking.starts_at - H2,
        )
    return q.order_by(Booking.starts_at).limit(1).with_for_update(skip_locked=True, of=Booking)


async def process_due(sessionmaker: async_sessionmaker, send: Sender, now: datetime | None = None) -> int:
    sent = 0
    for kind in ("24", "2"):
        while True:
            current = now or now_utc()
            async with sessionmaker() as session, session.begin():
                booking = await session.scalar(_due_query(kind, current))
                if booking is None:
                    break
                try:
                    await send(kind, booking)
                    sent += 1
                except (TelegramForbiddenError, TelegramNotFound) as e:
                    log.info("Нагадування %s для запису %s не доставлено: %s", kind, booking.id, e)
                if kind == "24":
                    booking.remind_24_sent_at = current
                else:
                    booking.remind_2_sent_at = current
    return sent


def telegram_sender(bot: Bot) -> Sender:
    async def send(kind: str, b: Booking) -> None:
        chat_id = b.client.tg_user_id
        if kind == "24":
            await bot.send_message(chat_id, texts.reminder_24(b), reply_markup=kb.reminder_24(b.id))
        else:
            await bot.send_message(chat_id, texts.reminder_2(b), reply_markup=kb.reminder_2())

    return send


async def run_forever(bot: Bot, sessionmaker: async_sessionmaker, interval: int) -> None:
    send = telegram_sender(bot)
    log.info("Воркер нагадувань запущено (інтервал %s с)", interval)
    while True:
        try:
            n = await process_due(sessionmaker, send)
            if n:
                log.info("Надіслано нагадувань: %s", n)
        except Exception:
            log.exception("Помилка воркера нагадувань")
        await asyncio.sleep(interval)
