from datetime import UTC, datetime

from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.security import decode_jwt, hash_api_token
from app.db.models import ApiToken, User
from app.db.session import get_session


def _unauth() -> AppError:
    return AppError("unauthorized", "Требуется авторизация.", 401)


async def current_user(
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> User:
    """Принимает JWT access-токен или API-токен расширения (`rsh_...`)."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise _unauth()
    token = authorization[7:].strip()

    if token.startswith("rsh_"):
        api_token = await session.scalar(
            select(ApiToken).where(
                ApiToken.token_hash == hash_api_token(token), ApiToken.revoked_at.is_(None)
            )
        )
        if api_token is None:
            raise _unauth()
        api_token.last_used_at = datetime.now(UTC)
        user = await session.get(User, api_token.user_id)
        await session.commit()
    else:
        user_id = decode_jwt(token, "access")
        user = await session.get(User, user_id) if user_id else None

    if user is None:
        raise _unauth()
    return user
