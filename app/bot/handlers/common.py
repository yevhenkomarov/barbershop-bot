from aiogram import Bot, F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

from app import texts
from app.bot import commands
from app.bot import keyboards as kb
from app.bot.callbacks import Menu
from app.bot.ui import show
from app.config import get_settings
from app.models import Master

router = Router(name="common")


@router.message(CommandStart())
async def cmd_start(
    message: Message, state: FSMContext, master: Master | None, is_admin: bool, bot: Bot
) -> None:
    if await state.get_state() is not None:
        await state.clear()
        await message.answer(texts.BACK_TO_MENU, reply_markup=ReplyKeyboardRemove())
    if master is not None or is_admin:
        await message.answer(texts.staff_hello(master, is_admin))
        await commands.set_staff(bot, message.chat.id)
    await message.answer(texts.welcome(), reply_markup=kb.main_menu())


@router.callback_query(Menu.filter(F.a == "main"))
async def main_menu(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await show(cb, texts.welcome(), kb.main_menu())


@router.callback_query(Menu.filter(F.a == "contacts"))
async def contacts(cb: CallbackQuery) -> None:
    await show(cb, texts.contacts(), kb.contacts())


@router.callback_query(Menu.filter(F.a == "map"))
async def send_map(cb: CallbackQuery) -> None:
    s = get_settings()
    await cb.message.answer_venue(
        latitude=s.shop_lat, longitude=s.shop_lon, title=s.shop_name, address=s.shop_address
    )
    await cb.answer()
