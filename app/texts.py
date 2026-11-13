from collections.abc import Sequence
from datetime import date, datetime
from html import escape

from app.config import get_settings
from app.core import fmt
from app.models import BLOCK, Booking, Master, Service

BTN_BOOK = "✂️ Записатися"
BTN_MY = "🗓 Мої візити"
BTN_CONTACTS = "📍 Як нас знайти"
BTN_BACK = "Назад"
BTN_MAIN = "У меню"
BTN_ANY_MASTER = "Будь-хто з майстрів"
BTN_MORE_DATES = "Далі →"
BTN_PREV_DATES = "← Раніше"
BTN_SHARE_CONTACT = "📱 Надіслати мій номер"
BTN_CONFIRM = "✅ Так, записати"
BTN_CHANGE = "✏️ Виправити"
BTN_SHOW_FREE = "Обрати інший час"
BTN_MAP = "🗺 Відкрити карту"
BTN_ROUTE = "🗺 Маршрут"
BTN_I_CONFIRM = "👍 Буду"
BTN_CANCEL_REM = "Не зможу"
BTN_YES_CANCEL = "Так, скасувати"
BTN_NO = "Залишити"
BTN_CHANGE_SERVICE = "Послугу"
BTN_CHANGE_MASTER = "Майстра"
BTN_CHANGE_DATETIME = "Дату й час"
BTN_CHANGE_NAME = "Імʼя"


def btn_service(s: Service) -> str:
    return f"{s.short_name} — {s.price} грн, {s.duration_min} хв"


def btn_cancel_n(n: int) -> str:
    return f"❌ Скасувати №{n}"


def welcome() -> str:
    s = get_settings()
    return (
        f"<b>{escape(s.shop_name)}</b>\n"
        f"📍 {escape(s.shop_address)}\n"
        f"🕙 {escape(s.shop_hours)}\n\n"
        "Тут можна записатися онлайн, переглянути або скасувати свій візит."
    )


CHOOSE_SERVICE = "Яка послуга вас цікавить?"
CHOOSE_MASTER = "До кого записати?"
CHOOSE_DATE = "Коли вам зручно?"
NO_SERVICES = "Онлайн-запис зараз недоступний. Зателефонуйте нам: {phone}"
NO_MASTERS = "Зараз ніхто з майстрів не виконує цю послугу."
NO_DATES = "Найближчим часом вільних вікон немає. Оберіть іншого майстра або зателефонуйте: {phone}"
SLOT_TAKEN = "Поки ви обирали, цей час уже зайняли. Оберіть, будь ласка, інший."
ASK_CONTACT = "Залиште номер телефону — подзвонимо, якщо щось зміниться.\nСкористайтеся кнопкою нижче."
CONTACT_HINT = f"Скористайтеся кнопкою «{BTN_SHARE_CONTACT}» 👇"
CONTACT_NOT_YOURS = "Потрібен саме ваш номер — надішліть його кнопкою нижче 👇"
CONTACT_SAVED = "Дякуємо, {name}!"
ASK_NAME = "Як до вас звертатися?"
NAME_INVALID = "Імʼя має бути від 1 до 60 символів. Спробуйте ще раз:"
WHAT_TO_CHANGE = "Що виправити?"
SESSION_EXPIRED = "Ця сторінка вже неактуальна. Почнімо заново."
BACK_TO_MENU = "Повертаємось у меню."
NO_UPCOMING = "Запланованих візитів немає."
CANCELLED_OK = "Візит скасовано. Чекаємо на вас іншим разом."
ALREADY_CANCELLED = "Цей візит уже скасовано."
STAFF_ONLY = "Команда доступна лише персоналу."


def choose_time(day: date, master_name: str | None) -> str:
    who = f" ({escape(master_name)})" if master_name else ""
    return f"Оберіть час на {fmt.d_long(day)}{who}:"


def summary(service: Service, master_name: str, start: datetime, client_name: str, predicted: bool) -> str:
    master_line = escape(master_name) + (" — оберемо автоматично" if predicted else "")
    return (
        "Ваш запис:\n"
        f"• {escape(service.name)}, {service.duration_min} хв\n"
        f"• Майстер: {master_line}\n"
        f"• {fmt.d_title(start)}, {fmt.hm(start)}\n"
        f"• {service.price} грн, оплата на місці\n"
        f"• Імʼя: {escape(client_name)}\n\n"
        "Усе правильно?"
    )


def booked(b: Booking) -> str:
    s = get_settings()
    return (
        f"Записали вас {fmt.d_at(b.starts_at)} о {fmt.hm(b.starts_at)} ✅\n"
        f"{escape(b.service.short_name)}, майстер {escape(b.master.name)}\n"
        f"📍 {escape(s.shop_address)}\n\n"
        "Нагадування надійде за добу і за дві години до візиту."
    )


def booking_line(b: Booking) -> str:
    return f"{fmt.d_short(b.starts_at)} {fmt.hm(b.starts_at)} · {escape(b.service.short_name)} · {escape(b.master.name)}"


def my_bookings(items: Sequence[tuple[Booking, bool]]) -> str:
    s = get_settings()
    lines = ["Заплановані візити:"]
    for i, (b, can_cancel) in enumerate(items, 1):
        lines.append(f"{i}. {booking_line(b)}")
        if not can_cancel:
            lines.append(f"   <i>Онлайн скасувати вже пізно — телефонуйте: {escape(s.shop_phone)}</i>")
    return "\n".join(lines)


def ask_cancel(b: Booking) -> str:
    return f"Точно скасувати?\n{booking_line(b)}"


def too_late_to_cancel() -> str:
    return f"Онлайн скасувати вже пізно — телефонуйте: {escape(get_settings().shop_phone)}"


def contacts() -> str:
    s = get_settings()
    lines = [
        f"<b>{escape(s.shop_name)}</b>",
        f"Адреса: {escape(s.shop_address)}",
        f"Графік: {escape(s.shop_hours)}",
        f"Телефон: {escape(s.shop_phone)}",
    ]
    if s.shop_instagram:
        ig = escape(s.shop_instagram.lstrip("@"))
        lines.append(f'Instagram: <a href="https://instagram.com/{ig}">@{ig}</a>')
    return "\n".join(lines)


def _reminder_24_body(b: Booking) -> str:
    return f"Завтра о {fmt.hm(b.starts_at)} у вас {escape(b.service.short_name)}, майстер {escape(b.master.name)}."


def reminder_24(b: Booking) -> str:
    return f"{_reminder_24_body(b)}\nУсе в силі?"


def reminder_24_confirmed(b: Booking) -> str:
    return f"{_reminder_24_body(b)}\n\n👍 Дякуємо, до зустрічі!"


def reminder_2(b: Booking) -> str:
    return (
        f"Сьогодні о {fmt.hm(b.starts_at)} ваш візит. До зустрічі!\n📍 {escape(get_settings().shop_address)}"
    )


def cancelled_by_admin_for_client(b: Booking) -> str:
    return (
        f"Адміністратор скасував ваш візит {fmt.d_short(b.starts_at)} {fmt.hm(b.starts_at)} "
        f"({escape(b.service.short_name)}).\n"
        f"Якщо це помилка, зателефонуйте: {escape(get_settings().shop_phone)}"
    )


def booked_by_admin_for_client(b: Booking) -> str:
    s = get_settings()
    return (
        f"Адміністратор записав вас {fmt.d_at(b.starts_at)} о {fmt.hm(b.starts_at)} ✅\n"
        f"{escape(b.service.short_name)}, майстер {escape(b.master.name)}\n"
        f"📍 {escape(s.shop_address)}"
    )


def _staff_line(b: Booking) -> str:
    return (
        f"{fmt.d_short(b.starts_at)} {fmt.hm(b.starts_at)}–{fmt.hm(b.ends_at)}, "
        f"{escape(b.service.short_name)}, {escape(b.master.name)}\n"
        f"{escape(b.client.name)}, {fmt.pretty_phone(b.client.phone)}"
    )


def staff_new(b: Booking) -> str:
    src = " з адмінки" if b.source == "admin" else ""
    return f"📥 Новий запис{src}\n{_staff_line(b)}"


def staff_cancelled(b: Booking) -> str:
    who = "клієнт" if b.cancelled_by == "client" else "адміністратор"
    return f"🚫 Скасував {who}\n{_staff_line(b)}"


def _agenda_line(b: Booking) -> str:
    span = f"{fmt.hm(b.starts_at)}–{fmt.hm(b.ends_at)}"
    if b.kind == BLOCK:
        return f"{span} · перерва" + (f" ({escape(b.note)})" if b.note else "")
    mark = " ✅" if b.confirmed_at else ""
    return f"{span} · {escape(b.service.short_name)} · {escape(b.client.name)}{mark}"


def agenda(day: date, bookings: Sequence[Booking], master: Master | None, when: str) -> str:
    head = f"Розклад на {when}, {fmt.d_compact(day)}:"
    if not bookings:
        return f"{head}\nЗаписів немає."
    if master is not None:
        return "\n".join([head, *(_agenda_line(b) for b in bookings)])
    lines = [head]
    current = None
    for b in bookings:
        if b.master_id != current:
            current = b.master_id
            lines.append(f"\n<b>{escape(b.master.name)}</b>")
        lines.append(_agenda_line(b))
    lines.append("\n✅ — клієнт підтвердив, що прийде")
    return "\n".join(lines)


def staff_hello(master: Master | None, is_admin: bool) -> str:
    roles = []
    if is_admin:
        roles.append("адміністратор")
    if master:
        roles.append(f"майстер {escape(master.name)}")
    return (
        f"Готово, ви в системі як {', '.join(roles)}.\n"
        "Сюди надходитимуть нові записи та скасування.\n\n"
        "/today — розклад на сьогодні\n"
        "/tomorrow — розклад на завтра"
    )
