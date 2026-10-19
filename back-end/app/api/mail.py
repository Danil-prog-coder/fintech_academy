from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.api.qa import require_askable_repo
from app.db.models import QuestionLog, User
from app.db.session import get_session
from app.llm.base import LLMProvider
from app.llm.deps import get_llm_optional
from app.schemas.common import ERROR_RESPONSES
from app.schemas.mail import MailAskRequest, MailAskResponse, QuestionResult
from app.services.mail import extract_questions, recommend
from app.services.qa import answer_question, question_hash

router = APIRouter(tags=["mail"], responses=ERROR_RESPONSES)


@router.post("/mail/ask", response_model=MailAskResponse)
async def mail_ask(
    body: MailAskRequest,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    llm: LLMProvider | None = Depends(get_llm_optional),
):
    """«Спросить у ИИ». Ничего не отправляет и не блокирует; текст письма не сохраняется."""
    repo = await require_askable_repo(session, user.id)

    # Переписка станет контекстом для LLM; пока её содержимое не используется и не хранится.
    history = [(m.author or "unknown", m.text) for m in body.thread]

    results: list[QuestionResult] = []
    last = None
    for question in extract_questions(body.draft):
        last = await answer_question(repo, question, history, llm)
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
