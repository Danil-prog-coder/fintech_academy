from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.api.qa import ASKABLE_STATUSES, require_askable_repo
from app.api.repo import get_user_repo
from app.core.ratelimit import per_user
from app.db.models import QuestionLog, User
from app.db.session import get_session
from app.llm.base import EmbeddingProvider, LLMProvider
from app.llm.deps import get_embeddings_optional, get_llm_optional
from app.schemas.common import ERROR_RESPONSES
from app.schemas.mail import (
    MailAskRequest,
    MailAskResponse,
    QuestionResult,
    ReplyDraftRequest,
    ReplyDraftResponse,
)
from app.services.mail import extract_questions, recommend
from app.services.qa import answer_question, question_hash
from app.services.reply import draft_reply

router = APIRouter(tags=["mail"], responses=ERROR_RESPONSES)


@router.post("/mail/ask", response_model=MailAskResponse)
async def mail_ask(
    body: MailAskRequest,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    llm: LLMProvider | None = Depends(get_llm_optional),
    embeddings: EmbeddingProvider | None = Depends(get_embeddings_optional),
    _: None = per_user("ask", 30),
):
    """«Спросить у ИИ». Ничего не отправляет и не блокирует; текст письма не сохраняется."""
    repo = await require_askable_repo(session, user.id)

    # Переписка станет контекстом для LLM; пока её содержимое не используется и не хранится.
    history = [(m.author or "unknown", m.text) for m in body.thread]

    results: list[QuestionResult] = []
    last = None
    for question in extract_questions(body.draft):
        last = await answer_question(session, repo, question, history, llm, embeddings)
        log = QuestionLog(
            user_id=user.id,
            source="mail",
            question_hash=question_hash(question),
            status=last.status,
        )
        session.add(log)
        await session.flush()
        results.append(
            QuestionResult(
                question_log_id=log.id,
                question=question,
                answer=last.answer,
                status=last.status,
                sources=last.sources,
            )
        )
    await session.commit()

    return MailAskResponse(
        results=results,
        recommendation=recommend([r.status for r in results]),
        index_commit=last.index_commit if last else None,
        provider=last.provider if last else None,
    )


@router.post("/mail/reply-draft", response_model=ReplyDraftResponse)
async def mail_reply_draft(
    body: ReplyDraftRequest,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    llm: LLMProvider | None = Depends(get_llm_optional),
    embeddings: EmbeddingProvider | None = Depends(get_embeddings_optional),
    _: None = per_user("ask", 30),
):
    """«Ответ с ИИ»: черновик ответа на последнее письмо переписки. Ничего не отправляет.

    Без готового индекса проекта черновик строится по одной переписке, а факты остаются
    пометками «уточнить». Текст писем не сохраняется.
    """
    repo = await get_user_repo(session, user.id)
    if repo is not None and repo.status not in ASKABLE_STATUSES:
        repo = None
    *earlier, letter = body.thread
    history = [(m.author or "unknown", m.text) for m in earlier]
    result = await draft_reply(
        session, repo, letter.text, body.subject, history, body.notes, llm, embeddings
    )

    log = QuestionLog(
        user_id=user.id,
        source="reply",
        question_hash=question_hash(letter.text),
        status="answered" if result.sources else "not_found",
    )
    session.add(log)
    await session.flush()
    log_id = log.id
    await session.commit()
    return ReplyDraftResponse(
        question_log_id=log_id,
        draft=result.draft,
        sources=result.sources,
        todo=result.todo,
        used_project=repo is not None,
        index_commit=result.index_commit,
        provider=result.provider,
    )
