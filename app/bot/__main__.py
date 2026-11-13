import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy import select

from app.bot import commands
from app.bot.handlers import booking, common, my, staff
from app.bot.middlewares import DbMiddleware
from app.config import get_settings
from app.core.notify import admin_chat_ids
from app.db import get_sessionmaker
from app.models import Master
from app.worker.reminders import run_forever

log = logging.getLogger("app.bot")


def build_bot() -> Bot:
    return Bot(get_settings().bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    dp.update.outer_middleware(DbMiddleware())
    dp.include_routers(common.router, staff.router, booking.router, my.router)
    return dp


async def set_commands(bot: Bot) -> None:
    await commands.set_default(bot)
    async with get_sessionmaker()() as session:
        ids = await admin_chat_ids(session)
        ids.update(
            (await session.scalars(select(Master.tg_user_id).where(Master.tg_user_id.is_not(None)))).all()
        )
    for chat_id in ids:
        await commands.set_staff(bot, chat_id)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = get_settings()
    if not settings.bot_token:
        raise SystemExit("BOT_TOKEN не задано (.env)")
    bot = build_bot()
    dp = build_dispatcher()
    await set_commands(bot)
    worker = asyncio.create_task(run_forever(bot, get_sessionmaker(), settings.reminder_poll_seconds))
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        worker.cancel()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
