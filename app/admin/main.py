import logging
import secrets
import time as _time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app.admin import routes
from app.config import get_settings
from app.core import fmt

log = logging.getLogger(__name__)
TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
TEMPLATES.env.globals.update(fmt=fmt, settings=get_settings)


class NotAuthenticated(Exception):
    pass


def require_admin(request: Request) -> None:
    if not request.session.get("admin"):
        raise NotAuthenticated


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    app.state.bot = (
        Bot(s.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML)) if s.bot_token else None
    )
    if not s.admin_password:
        log.warning("ADMIN_PASSWORD не задано — увійти в адмінку неможливо")
    yield
    if app.state.bot:
        await app.state.bot.session.close()


app = FastAPI(title="Адмін-панель", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=get_settings().admin_secret_key,
    session_cookie="barber_admin",
    max_age=7 * 24 * 3600,
    same_site="lax",
    https_only=get_settings().admin_https_only,
)


@app.exception_handler(NotAuthenticated)
async def _to_login(request: Request, exc: NotAuthenticated):
    nxt = request.url.path + (f"?{request.url.query}" if request.url.query else "")
    return RedirectResponse(f"/login?next={quote(nxt)}", status_code=303)


_failures: dict[str, deque] = defaultdict(deque)
MAX_FAILURES, WINDOW = 5, 300


def _locked(ip: str) -> bool:
    q = _failures[ip]
    while q and q[0] < _time.monotonic() - WINDOW:
        q.popleft()
    return len(q) >= MAX_FAILURES


@app.get("/login", response_class=HTMLResponse)
async def login_form(request: Request, next: str = "/"):
    return TEMPLATES.TemplateResponse(request, "login.html", {"next": next, "error": None})


@app.post("/login", response_class=HTMLResponse)
async def login(request: Request):
    form = await request.form()
    nxt = str(form.get("next") or "/")
    if not nxt.startswith("/") or nxt.startswith("//"):
        nxt = "/"
    ip = request.client.host if request.client else "?"
    s = get_settings()
    error = None
    if _locked(ip):
        error = "Забагато спроб. Зачекайте 5 хвилин."
    elif not s.admin_password:
        error = "Пароль адміністратора не налаштовано (ADMIN_PASSWORD у .env)."
    elif secrets.compare_digest(str(form.get("login", "")), s.admin_login) and secrets.compare_digest(
        str(form.get("password", "")), s.admin_password
    ):
        request.session.clear()
        request.session["admin"] = True
        return RedirectResponse(nxt, status_code=303)
    else:
        _failures[ip].append(_time.monotonic())
        error = "Невірний логін або пароль."
    return TEMPLATES.TemplateResponse(request, "login.html", {"next": nxt, "error": error}, status_code=401)


@app.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@app.get("/health")
async def health():
    return {"ok": True}


app.include_router(routes.build_router(TEMPLATES), dependencies=[Depends(require_admin)])
