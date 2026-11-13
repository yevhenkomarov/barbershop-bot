from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User
from sqlalchemy import func, select

from app.core.notify import is_admin
from app.db import get_sessionmaker
from app.models import Client, Master


class DbMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user")
        async with get_sessionmaker()() as session:
            data["session"] = session
            if user is not None and not user.is_bot:
                data["client"] = await _upsert_client(session, user)
                data["master"] = await _link_master(session, user)
                data["is_admin"] = is_admin(user.id, user.username)
                await session.commit()
            return await handler(event, data)


async def _upsert_client(session, user: User) -> Client:
    client = await session.scalar(select(Client).where(Client.tg_user_id == user.id))
    if client is None:
        name = " ".join(x for x in (user.first_name, user.last_name) if x)[:100]
        client = Client(tg_user_id=user.id, tg_username=user.username, name=name)
        session.add(client)
        await session.flush()
    elif client.tg_username != user.username:
        client.tg_username = user.username
    return client


async def _link_master(session, user: User) -> Master | None:
    master = await session.scalar(select(Master).where(Master.tg_user_id == user.id))
    if master is not None:
        return master
    if not user.username:
        return None
    master = await session.scalar(
        select(Master).where(
            func.lower(Master.tg_username) == user.username.lower(), Master.tg_user_id.is_(None)
        )
    )
    if master is not None:
        master.tg_user_id = user.id
    return master
