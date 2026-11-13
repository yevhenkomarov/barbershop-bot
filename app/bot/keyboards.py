from collections.abc import Sequence
from datetime import date, datetime

from aiogram.types import InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app import texts
from app.bot.callbacks import Bk, Menu, My, Rem
from app.config import get_settings
from app.core import fmt
from app.models import Booking, Master, Service

DATES_PER_PAGE = 6


def main_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=texts.BTN_BOOK, callback_data=Menu(a="book"))
    kb.button(text=texts.BTN_MY, callback_data=Menu(a="my"))
    kb.button(text=texts.BTN_CONTACTS, callback_data=Menu(a="contacts"))
    kb.adjust(1, 2)
    return kb.as_markup()


def services(items: Sequence[Service]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for s in items:
        kb.button(text=texts.btn_service(s), callback_data=Bk(st="mst", s=s.id))
    kb.button(text=texts.BTN_BACK, callback_data=Menu(a="main"))
    kb.adjust(1)
    return kb.as_markup()


def masters(service_id: int, items: Sequence[Master]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for m in items:
        kb.button(text=m.name, callback_data=Bk(st="date", s=service_id, m=m.id))
    sizes = [3] * (len(items) // 3) + ([len(items) % 3] if len(items) % 3 else [])
    if len(items) > 1:
        kb.button(text=texts.BTN_ANY_MASTER, callback_data=Bk(st="date", s=service_id, m=0))
        sizes.append(1)
    kb.button(text=texts.BTN_BACK, callback_data=Bk(st="svc"))
    sizes.append(1)
    kb.adjust(*sizes)
    return kb.as_markup()


def dates(cb: Bk, days: Sequence[date], page: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    chunk = days[page * DATES_PER_PAGE : (page + 1) * DATES_PER_PAGE]
    for d in chunk:
        kb.button(text=fmt.d_short(d), callback_data=Bk(st="time", s=cb.s, m=cb.m, d=fmt.d_key(d), p=page))
    sizes = [3] * (len(chunk) // 3) + ([len(chunk) % 3] if len(chunk) % 3 else [])
    nav = 0
    if page > 0:
        kb.button(text=texts.BTN_PREV_DATES, callback_data=Bk(st="date", s=cb.s, m=cb.m, p=page - 1))
        nav += 1
    if (page + 1) * DATES_PER_PAGE < len(days):
        kb.button(text=texts.BTN_MORE_DATES, callback_data=Bk(st="date", s=cb.s, m=cb.m, p=page + 1))
        nav += 1
    if nav:
        sizes.append(nav)
    kb.button(text=texts.BTN_BACK, callback_data=Bk(st="mst", s=cb.s))
    sizes.append(1)
    kb.adjust(*sizes)
    return kb.as_markup()


def times(cb: Bk, slots: Sequence[datetime]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for t in slots:
        kb.button(text=fmt.hm(t), callback_data=Bk(st="sum", s=cb.s, m=cb.m, d=cb.d, t=fmt.t_key(t)))
    sizes = [4] * (len(slots) // 4) + ([len(slots) % 4] if len(slots) % 4 else [])
    kb.button(text=texts.BTN_BACK, callback_data=Bk(st="date", s=cb.s, m=cb.m, p=cb.p))
    kb.adjust(*sizes, 1)
    return kb.as_markup()


def contact_request() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=texts.BTN_SHARE_CONTACT, request_contact=True)],
            [KeyboardButton(text=texts.BTN_BACK)],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def summary(cb: Bk) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=texts.BTN_CONFIRM, callback_data=Bk(st="ok", s=cb.s, m=cb.m, d=cb.d, t=cb.t))
    kb.button(text=texts.BTN_CHANGE, callback_data=Bk(st="chg", s=cb.s, m=cb.m, d=cb.d, t=cb.t))
    kb.button(text=texts.BTN_BACK, callback_data=Bk(st="time", s=cb.s, m=cb.m, d=cb.d))
    kb.adjust(1, 2)
    return kb.as_markup()


def change_menu(cb: Bk) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=texts.BTN_CHANGE_SERVICE, callback_data=Bk(st="svc"))
    kb.button(text=texts.BTN_CHANGE_MASTER, callback_data=Bk(st="mst", s=cb.s))
    kb.button(text=texts.BTN_CHANGE_DATETIME, callback_data=Bk(st="date", s=cb.s, m=cb.m))
    kb.button(text=texts.BTN_CHANGE_NAME, callback_data=Bk(st="name", s=cb.s, m=cb.m, d=cb.d, t=cb.t))
    kb.button(text=texts.BTN_BACK, callback_data=Bk(st="sum", s=cb.s, m=cb.m, d=cb.d, t=cb.t))
    kb.adjust(2, 2, 1)
    return kb.as_markup()


def back_to_summary(cb: Bk) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=texts.BTN_BACK, callback_data=Bk(st="sum", s=cb.s, m=cb.m, d=cb.d, t=cb.t))
    return kb.as_markup()


def slot_taken(cb: Bk) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=texts.BTN_SHOW_FREE, callback_data=Bk(st="time", s=cb.s, m=cb.m, d=cb.d))
    return kb.as_markup()


def after_booking() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=texts.BTN_MY, callback_data=Menu(a="my"))
    kb.button(text=texts.BTN_MAIN, callback_data=Menu(a="main"))
    kb.adjust(2)
    return kb.as_markup()


def only_main() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=texts.BTN_MAIN, callback_data=Menu(a="main"))
    return kb.as_markup()


def no_bookings() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=texts.BTN_BOOK, callback_data=Menu(a="book"))
    kb.button(text=texts.BTN_MAIN, callback_data=Menu(a="main"))
    kb.adjust(2)
    return kb.as_markup()


def my_bookings(items: Sequence[tuple[Booking, bool]]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for i, (b, can_cancel) in enumerate(items, 1):
        if can_cancel:
            kb.button(text=texts.btn_cancel_n(i), callback_data=My(a="ask", id=b.id))
    kb.button(text=texts.BTN_MAIN, callback_data=Menu(a="main"))
    kb.adjust(1)
    return kb.as_markup()


def ask_cancel(booking_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=texts.BTN_YES_CANCEL, callback_data=My(a="yes", id=booking_id))
    kb.button(text=texts.BTN_NO, callback_data=My(a="no", id=booking_id))
    kb.adjust(2)
    return kb.as_markup()


def contacts() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=texts.BTN_MAP, callback_data=Menu(a="map"))
    kb.button(text=texts.BTN_MAIN, callback_data=Menu(a="main"))
    kb.adjust(1)
    return kb.as_markup()


def reminder_24(booking_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=texts.BTN_I_CONFIRM, callback_data=Rem(a="ok", id=booking_id))
    kb.button(text=texts.BTN_CANCEL_REM, callback_data=Rem(a="cancel", id=booking_id))
    kb.adjust(2)
    return kb.as_markup()


def reminder_2() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=texts.BTN_ROUTE, url=get_settings().route_url)
    return kb.as_markup()
