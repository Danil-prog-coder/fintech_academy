import json
from collections.abc import Iterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.api.repo import get_user_repo
from app.core.errors import AppError
from app.db.models import Conversation, Message, QuestionLog, Repository, User
from app.db.session import get_session
from app.schemas.common import ERROR_RESPONSES, Source
from app.schemas.qa import AnswerResponse, AskRequest, ConversationOut, MessageOut
from app.services.qa import answer_question, question_hash

router = APIRouter(tags=["qa"], responses=ERROR_RESPONSES)

# Пока идёт обновление или отозван токен, ответы строятся по прежнему индексу (FR-IDX-05).
ASKABLE_STATUSES = {"ready", "updating", "reauth_required"}


async def require_askable_repo(session: AsyncSession, user_id: int) -> Repository:
    repo = await get_user_repo(session, user_id)
    if repo is None:
        raise AppError("repo_not_connected", "Сначала подключите репозиторий.", 409)
    if repo.status not in ASKABLE_STATUSES:
        raise AppError(
            "index_not_ready", "Индекс ещё не готов. Попробуйте позже.", 409, retryable=True
        )
    return repo


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _stream(result: AnswerResponse) -> Iterator[str]:
    # Формат потока зафиксирован для клиентов; настоящая потоковая генерация появится с LLM-слоем.
    yield _sse("status", {"stage": "searching", "message": "Ищем в проекте…"})
    yield _sse("answer", {"delta": result.answer})
    yield _sse("done", result.model_dump(mode="json"))


@router.post(
    "/qa/ask",
    response_model=AnswerResponse,
    responses={200: {"content": {"text/event-stream": {}}, "description": "stream=true — SSE"}},
)
async def ask(
    body: AskRequest,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    repo = await require_askable_repo(session, user.id)

    if body.conversation_id is None:
        conversation = Conversation(user_id=user.id)
        session.add(conversation)
        await session.flush()
        history: list[tuple[str, str]] = []
    else:
        conversation = await session.get(Conversation, body.conversation_id)
        if conversation is None or conversation.user_id != user.id:
            raise AppError("conversation_not_found", "Диалог не найден.", 404)
        rows = await session.scalars(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.id)
        )
        history = [(m.role, m.text) for m in rows]

    result = await answer_question(repo, body.question, history)

    session.add(Message(conversation_id=conversation.id, role="user", text=body.question))
    reply = Message(
        conversation_id=conversation.id,
        role="assistant",
        text=result.answer,
        sources=[s.model_dump() for s in result.sources],
        status=result.status,
    )
    session.add(reply)
    session.add(
        QuestionLog(
            user_id=user.id,
            source="chat",
            question_hash=question_hash(body.question),
            status=result.status,
        )
    )
    await session.commit()

    response = AnswerResponse(
        conversation_id=conversation.id,
        message_id=reply.id,
        answer=result.answer,
        status=result.status,
        sources=result.sources,
        index_commit=result.index_commit,
        provider=result.provider,
    )
    if body.stream:
        return StreamingResponse(_stream(response), media_type="text/event-stream")
    return response


@router.get("/qa/conversations/{conversation_id}", response_model=ConversationOut)
async def get_conversation(
    conversation_id: int,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None or conversation.user_id != user.id:
        raise AppError("conversation_not_found", "Диалог не найден.", 404)
    rows = await session.scalars(
        select(Message).where(Message.conversation_id == conversation.id).order_by(Message.id)
    )
    return ConversationOut(
        id=conversation.id,
        created_at=conversation.created_at,
        messages=[
            MessageOut(
                id=m.id,
                role=m.role,
                text=m.text,
                sources=[Source(**s) for s in m.sources],
                status=m.status,
                created_at=m.created_at,
            )
            for m in rows
        ],
    )


@router.get("/sources/{source_id}", response_model=Source)
async def get_source(source_id: int, user: User = Depends(current_user)):
    # Фрагменты (chunks) появятся вместе с индексацией; пока источников не существует.
    raise AppError("source_not_found", "Источник не найден.", 404)
