import logging

from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault

log = logging.getLogger(__name__)

CLIENT = [BotCommand(command="start", description="Меню")]
STAFF = [
    *CLIENT,
    BotCommand(command="today", description="Розклад на сьогодні"),
    BotCommand(command="tomorrow", description="Розклад на завтра"),
]


async def set_default(bot: Bot) -> None:
    await bot.set_my_commands(CLIENT, scope=BotCommandScopeDefault())


async def set_staff(bot: Bot, chat_id: int) -> None:
    try:
        await bot.set_my_commands(STAFF, scope=BotCommandScopeChat(chat_id=chat_id))
    except Exception as e:
        log.warning("Не вдалося встановити команди для %s: %s", chat_id, e)
