from aiogram.filters.callback_data import CallbackData


class Menu(CallbackData, prefix="m"):
    a: str


class Bk(CallbackData, prefix="b"):
    st: str
    s: int = 0
    m: int = 0
    d: str = ""
    t: str = ""
    p: int = 0


class My(CallbackData, prefix="my"):
    a: str
    id: int


class Rem(CallbackData, prefix="r"):
    a: str
    id: int
