from datetime import date, datetime

from app.config import get_settings

WD_SHORT = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Нд"]
WD_NOM = ["понеділок", "вівторок", "середа", "четвер", "пʼятниця", "субота", "неділя"]
WD_ACC = ["понеділок", "вівторок", "середу", "четвер", "пʼятницю", "суботу", "неділю"]
MONTHS_GEN = [
    "січня", "лютого", "березня", "квітня", "травня", "червня",
    "липня", "серпня", "вересня", "жовтня", "листопада", "грудня",
]  # fmt: skip


def local(dt: datetime) -> datetime:
    return dt.astimezone(get_settings().tz)


def hm(dt: datetime) -> str:
    return local(dt).strftime("%H:%M")


def d_short(d: date | datetime) -> str:
    if isinstance(d, datetime):
        d = local(d).date()
    return f"{WD_SHORT[d.weekday()]} {d:%d.%m}"


def d_long(d: date | datetime) -> str:
    if isinstance(d, datetime):
        d = local(d).date()
    return f"{d.day} {MONTHS_GEN[d.month - 1]}"


def d_at(d: date | datetime) -> str:
    if isinstance(d, datetime):
        d = local(d).date()
    return f"у {WD_ACC[d.weekday()]}, {d_long(d)}"


def d_title(d: date | datetime) -> str:
    if isinstance(d, datetime):
        d = local(d).date()
    return f"{WD_NOM[d.weekday()].capitalize()}, {d_long(d)}"


def d_compact(d: date) -> str:
    return f"{WD_NOM[d.weekday()]} {d:%d.%m}"


def d_key(d: date) -> str:
    return d.strftime("%Y%m%d")


def parse_d_key(s: str) -> date:
    return datetime.strptime(s, "%Y%m%d").date()


def t_key(dt: datetime) -> str:
    return local(dt).strftime("%H%M")


def normalize_phone(raw: str) -> str:
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) == 10 and digits.startswith("0"):
        digits = "38" + digits
    return f"+{digits}" if digits else ""


def pretty_phone(phone: str | None) -> str:
    if not phone:
        return "—"
    d = "".join(ch for ch in phone if ch.isdigit())
    if len(d) == 12 and d.startswith("380"):
        return f"+{d[:3]} {d[3:5]} {d[5:8]} {d[8:10]} {d[10:]}"
    return phone
