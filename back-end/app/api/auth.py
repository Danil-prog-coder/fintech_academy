from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.errors import AppError
from app.core.security import (
    create_jwt,
    decode_jwt,
    hash_password,
    new_api_token,
    verify_password,
)
from app.db.models import ApiToken, Repository, User
from app.db.session import get_session

router = APIRouter(tags=["auth"])


class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str


class RefreshRequest(BaseModel):
    refresh_token: str


class ApiTokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class ApiTokenCreated(BaseModel):
    id: int
    name: str
    token: str  # показывается один раз


class MeResponse(BaseModel):
    id: int
    email: str
    repo_status: str = "not_connected"


def _pair(user_id: int) -> TokenPair:
    return TokenPair(
        access_token=create_jwt(user_id, "access"), refresh_token=create_jwt(user_id, "refresh")
    )


@router.post("/auth/register", response_model=TokenPair, status_code=201)
async def register(body: Credentials, session: AsyncSession = Depends(get_session)):
    user = User(email=body.email.lower(), password_hash=await hash_password(body.password))
    session.add(user)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise AppError("email_taken", "Пользователь с таким email уже существует.", 409)
    return _pair(user.id)


@router.post("/auth/login", response_model=TokenPair)
async def login(body: Credentials, session: AsyncSession = Depends(get_session)):
    user = await session.scalar(select(User).where(User.email == body.email.lower()))
    # Одинаковая ошибка для неверного email и пароля.
    if user is None or not await verify_password(body.password, user.password_hash):
        raise AppError("invalid_credentials", "Неверный email или пароль.", 401)
    return _pair(user.id)


@router.post("/auth/refresh", response_model=TokenPair)
async def refresh(body: RefreshRequest, session: AsyncSession = Depends(get_session)):
    user_id = decode_jwt(body.refresh_token, "refresh")
    if user_id is None or await session.get(User, user_id) is None:
        raise AppError("invalid_token", "Токен недействителен или истёк.", 401)
    return _pair(user_id)


@router.post("/auth/api-tokens", response_model=ApiTokenCreated, status_code=201)
async def create_api_token(
    body: ApiTokenCreate,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    raw, token_hash = new_api_token()
    row = ApiToken(user_id=user.id, token_hash=token_hash, name=body.name)
    session.add(row)
    await session.commit()
    return ApiTokenCreated(id=row.id, name=row.name, token=raw)


@router.delete("/auth/api-tokens/{token_id}", status_code=204)
async def revoke_api_token(
    token_id: int,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    row = await session.get(ApiToken, token_id)
    if row is None or row.user_id != user.id:
        raise AppError("not_found", "Токен не найден.", 404)
    row.revoked_at = datetime.now(UTC)
    await session.commit()


@router.get("/me", response_model=MeResponse)
async def me(
    user: User = Depends(current_user), session: AsyncSession = Depends(get_session)
):
    repo = await session.scalar(select(Repository).where(Repository.user_id == user.id))
    return MeResponse(
        id=user.id, email=user.email, repo_status=repo.status if repo else "not_connected"
    )
