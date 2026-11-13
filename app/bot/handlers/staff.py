from datetime import timedelta

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app import texts
from app.core import booking as svc
from app.models import Master

router = Router(name="staff")


async def _agenda(
    message: Message, session: AsyncSession, master: Master | None, is_admin: bool, offset: int
) -> None:
    if master is None and not is_admin:
        await message.answer(texts.STAFF_ONLY)
        return
    day = svc.local_now().date() + timedelta(days=offset)
    when = "сьогодні" if offset == 0 else "завтра"
    if is_admin:
        items = await svc.day_agenda(session, day)
        await message.answer(texts.agenda(day, items, None, when))
    else:
        items = await svc.day_agenda(session, day, master.id)
        await message.answer(texts.agenda(day, items, master, when))


@router.message(Command("today"))
async def today(message: Message, session: AsyncSession, master: Master | None, is_admin: bool) -> None:
    await _agenda(message, session, master, is_admin, 0)


@router.message(Command("tomorrow"))
async def tomorrow(message: Message, session: AsyncSession, master: Master | None, is_admin: bool) -> None:
    await _agenda(message, session, master, is_admin, 1)
