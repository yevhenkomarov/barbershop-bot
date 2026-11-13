import itertools
from collections.abc import AsyncGenerator
from datetime import datetime

import pytest
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.methods import TelegramMethod
from aiogram.types import CallbackQuery, Chat, Contact, InlineKeyboardMarkup, Message, Update, User
from sqlalchemy import select

from app import texts
from app.bot.callbacks import Menu
from app.config import get_settings
from app.db import get_engine, get_sessionmaker
from app.models import ACTIVE, CANCELLED, Booking, Client, Master

BOT_ID = 42
_ids = itertools.count(1)


class FakeTelegram(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls: list[TelegramMethod] = []
        self.focus: int | None = None

    async def make_request(self, bot, method, timeout=None):  # noqa: ASYNC109
        self.calls.append(method)
        name = type(method).__name__
        if name in ("SendMessage", "EditMessageText", "SendVenue"):
            return Message(
                message_id=next(_ids),
                date=datetime.now(),
                chat=Chat(id=getattr(method, "chat_id", None) or 1, type="private"),
                from_user=User(id=BOT_ID, is_bot=True, first_name="Бот"),
                text=getattr(method, "text", None),
                reply_markup=markup
                if isinstance(markup := getattr(method, "reply_markup", None), InlineKeyboardMarkup)
                else None,
            )
        return True

    async def close(self):
        pass

    async def stream_content(self, *args, **kwargs) -> AsyncGenerator[bytes, None]:
        yield b""

    def sent_to(self, chat_id: int) -> list[str]:
        return [m.text for m in self.calls if type(m).__name__ == "SendMessage" and m.chat_id == chat_id]

    def last_screen(self):
        for m in reversed(self.calls):
            if type(m).__name__ in ("SendMessage", "EditMessageText") and m.chat_id == self.focus:
                return m
        raise AssertionError("бот нічого не показав")

    def button(self, text_startswith: str) -> str:
        markup = self.last_screen().reply_markup
        for row in markup.inline_keyboard:
            for b in row:
                if b.text.startswith(text_startswith):
                    return b.callback_data
        raise AssertionError(
            f"немає кнопки «{text_startswith}» у {[b.text for r in markup.inline_keyboard for b in r]}"
        )

    def buttons(self) -> list[str]:
        markup = self.last_screen().reply_markup
        return (
            [b.text for r in markup.inline_keyboard for b in r]
            if markup and hasattr(markup, "inline_keyboard")
            else []
        )


class Chatter:
    def __init__(self, dp, bot, tg: FakeTelegram, user_id: int, username: str, first_name: str):
        self.dp, self.bot, self.tg = dp, bot, tg
        self.user = User(id=user_id, is_bot=False, first_name=first_name, username=username)
        self.chat = Chat(id=user_id, type="private")

    async def say(self, text: str | None = None, contact: Contact | None = None):
        self.tg.focus = self.chat.id
        msg = Message(
            message_id=next(_ids),
            date=datetime.now(),
            chat=self.chat,
            from_user=self.user,
            text=text,
            contact=contact,
        )
        await self.dp.feed_update(self.bot, Update(update_id=next(_ids), message=msg))

    async def tap(self, callback_data: str):
        self.tg.focus = self.chat.id
        screen = Message(message_id=next(_ids), date=datetime.now(), chat=self.chat,
                         from_user=User(id=BOT_ID, is_bot=True, first_name="Бот"), text="…")  # fmt: skip
        cq = CallbackQuery(
            id=str(next(_ids)), from_user=self.user, chat_instance="ci", data=callback_data, message=screen
        )
        await self.dp.feed_update(self.bot, Update(update_id=next(_ids), callback_query=cq))


_DP = None


def dispatcher():
    global _DP
    if _DP is None:
        from app.bot.__main__ import build_dispatcher

        _DP = build_dispatcher()
    return _DP


@pytest.fixture
async def bot_env(shop, migrated, monkeypatch):
    monkeypatch.setenv("ADMIN_TELEGRAM", "@shop_admin")
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()
    tg = FakeTelegram()
    bot = Bot("42:TEST", session=tg, default=DefaultBotProperties(parse_mode="HTML"))
    yield dispatcher(), bot, tg
    await get_engine().dispose()
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()
    get_settings.cache_clear()


async def test_full_booking_flow(bot_env, sm):
    dp, bot, tg = bot_env
    roman = Chatter(dp, bot, tg, 900, "Roman_Master", "Роман")
    admin = Chatter(dp, bot, tg, 901, "shop_admin", "Власник")
    ostap = Chatter(dp, bot, tg, 500, "ostap", "Остап")

    await roman.say("/start")
    assert any("майстер Роман" in t for t in tg.sent_to(900))
    await admin.say("/start")
    assert any("адміністратор" in t for t in tg.sent_to(901))

    await ostap.say("/start")
    assert tg.last_screen().text == texts.welcome()
    assert tg.buttons() == [texts.BTN_BOOK, texts.BTN_MY, texts.BTN_CONTACTS]

    await ostap.tap(tg.button(texts.BTN_BOOK))
    assert tg.last_screen().text == texts.CHOOSE_SERVICE
    assert tg.buttons() == [
        "Стрижка — 500 грн, 60 хв",
        "Борода — 300 грн, 30 хв",
        "Комбо — 750 грн, 90 хв",
        texts.BTN_BACK,
    ]

    await ostap.tap(tg.button("Комбо"))
    assert tg.buttons() == [
        "Денис",
        "Роман",
        texts.BTN_ANY_MASTER,
        texts.BTN_BACK,
    ]

    await ostap.tap(tg.button("Роман"))
    assert tg.last_screen().text == texts.CHOOSE_DATE
    date_buttons = tg.buttons()
    assert texts.BTN_BACK in date_buttons and len(date_buttons) >= 4

    await ostap.tap(tg.button(date_buttons[1]))
    assert "Оберіть час на" in tg.last_screen().text and "(Роман)" in tg.last_screen().text
    first_time = tg.buttons()[0]

    await ostap.tap(tg.button(first_time))
    assert tg.last_screen().text == texts.ASK_CONTACT
    assert tg.last_screen().reply_markup.keyboard[0][0].request_contact is True

    await ostap.say(contact=Contact(phone_number="+380000000000", first_name="Хтось", user_id=777))
    assert tg.last_screen().text == texts.CONTACT_NOT_YOURS

    await ostap.say(
        contact=Contact(phone_number="380509998877", first_name="Остап", last_name="Вишня", user_id=500)
    )
    summary = tg.last_screen().text
    assert summary.startswith("Ваш запис:")
    assert "Стрижка й борода, 90 хв" in summary and "Майстер: Роман" in summary
    assert f", {first_time}" in summary and "750 грн, оплата на місці" in summary and "Остап Вишня" in summary

    await ostap.tap(tg.button(texts.BTN_CONFIRM))
    done = tg.last_screen().text
    assert done.startswith("Записали вас у") and f"о {first_time}" in done

    async with sm() as s:
        b = (await s.scalars(select(Booking))).one()
        client = await s.get(Client, b.client_id)
        master = await s.get(Master, b.master_id)
        assert (client.phone, client.name, master.name, b.status) == (
            "+380509998877",
            "Остап Вишня",
            "Роман",
            ACTIVE,
        )
        assert master.tg_user_id == 900

    assert any(t.startswith("📥 Новий запис") and "+380 50 999 88 77" in t for t in tg.sent_to(900))
    assert any(t.startswith("📥 Новий запис") for t in tg.sent_to(901))

    await ostap.tap(tg.button(texts.BTN_MAIN))
    await ostap.tap(tg.button(texts.BTN_BOOK))
    await ostap.tap(tg.button("Борода"))
    await ostap.tap(tg.button(texts.BTN_ANY_MASTER))
    await ostap.tap(tg.button(tg.buttons()[0]))
    await ostap.tap(tg.button(tg.buttons()[0]))
    assert tg.last_screen().text.startswith("Ваш запис:")
    assert "оберемо автоматично" in tg.last_screen().text

    await roman.say("/today")
    assert tg.last_screen().text.startswith("Розклад на сьогодні")
    await ostap.say("/today")
    assert tg.last_screen().text == texts.STAFF_ONLY

    n_before = len(tg.sent_to(900))
    await ostap.tap(Menu(a="my").pack())
    assert tg.last_screen().text.startswith("Заплановані візити:\n1. ")
    await ostap.tap(tg.button(texts.btn_cancel_n(1)))
    assert tg.last_screen().text.startswith("Точно скасувати?")
    await ostap.tap(tg.button(texts.BTN_YES_CANCEL))
    assert tg.last_screen().text.startswith(texts.CANCELLED_OK)
    async with sm() as s:
        assert (await s.scalars(select(Booking.status))).one() == CANCELLED
    assert any(t.startswith("🚫 Скасував клієнт") for t in tg.sent_to(900)[n_before:])


async def test_slot_taken_while_on_summary(bot_env, sm, shop):
    dp, bot, tg = bot_env
    bohdan = Chatter(dp, bot, tg, 111, "bohdan", "Богдан")
    await bohdan.say("/start")
    await bohdan.tap(tg.button(texts.BTN_BOOK))
    await bohdan.tap(tg.button("Борода"))
    await bohdan.tap(tg.button("Денис"))
    await bohdan.tap(tg.button(tg.buttons()[0]))
    await bohdan.tap(tg.button(tg.buttons()[0]))
    assert tg.last_screen().text.startswith("Ваш запис:")
    confirm = tg.button(texts.BTN_CONFIRM)

    from app.bot.callbacks import Bk
    from app.core import booking as svc

    cbd = Bk.unpack(confirm)
    async with sm() as s:
        start = datetime.strptime(cbd.d + cbd.t, "%Y%m%d%H%M").replace(tzinfo=get_settings().tz)
        await svc.create_booking(
            s, service=shop["beard"], master_id=shop["denys"].id, start=start, client=shop["nazar"]
        )
        await s.commit()

    await bohdan.tap(confirm)
    assert tg.last_screen().text == texts.SLOT_TAKEN
    assert tg.buttons() == [texts.BTN_SHOW_FREE]
