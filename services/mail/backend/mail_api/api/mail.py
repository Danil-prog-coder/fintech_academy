from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from mail_api.api.deps import current_user
from mail_api.api.platform import current_project, platform
from mail_api.core.ratelimit import per_user
from mail_api.db.models import User
from mail_api.db.session import get_session
from mail_api.schemas.common import ERROR_RESPONSES
from mail_api.schemas.mail import (
    MailAskRequest,
    MailAskResponse,
    QuestionResult,
    ReplyDraftRequest,
    ReplyDraftResponse,
    Source,
)
from mail_api.services.mail import build_reply, extract_questions, recommend
from mail_api.services.platform import PlatformClient, external_id

router = APIRouter(tags=["mail"], responses=ERROR_RESPONSES)

THREAD_CONTEXT_CHARS = 1500


def _with_context(question: str, subject: str | None, thread_tail: str) -> str:
    """The platform answers one question; the subject and the end of the thread help it understand which."""
    parts = [question]
    if subject:
        parts.append(f"(тема письма: {subject.strip()[:200]})")
    if thread_tail:
        parts.append(f"(из переписки: {thread_tail})")
    return "\n".join(parts)[:4000]


def _result(question: str, r: dict) -> QuestionResult:
    return QuestionResult(
        question=question, request_id=r.get("request_id"), action=r.get("action", "offer_operator"),
        answer=r.get("text", ""), confidence_level=r.get("confidence_level"),
        sources=[Source(label=s.get("citation_label"), document_title=s.get("document_title"),
                        section_path=s.get("section_path"), excerpt=s.get("excerpt"), url=s.get("url"))
                 for s in r.get("sources") or []])


@router.post("/mail/ask", response_model=MailAskResponse)
async def mail_ask(body: MailAskRequest, user: User = Depends(current_user), session: AsyncSession = Depends(get_session),
                   p: PlatformClient = Depends(platform), _: None = per_user("ask", 30)):
    """«Спросить у ИИ»: вопросы из черновика уходят в проект на платформе. Ничего не отправляет и не сохраняет."""
    pid = await current_project(session, user, p)
    tail = " ".join(m.text for m in body.thread[-2:])[-THREAD_CONTEXT_CHARS:].strip()
    results: list[QuestionResult] = []
    for question in extract_questions(body.draft):
        r = await p.ask(pid, external_id(user.id), _with_context(question, body.subject, tail), channel="mail")
        results.append(_result(question, r))
    return MailAskResponse(project_id=pid, results=results, recommendation=recommend([r.action for r in results]))


@router.post("/mail/reply-draft", response_model=ReplyDraftResponse)
async def mail_reply_draft(body: ReplyDraftRequest, user: User = Depends(current_user),
                           session: AsyncSession = Depends(get_session), p: PlatformClient = Depends(platform),
                           _: None = per_user("ask", 30)):
    """«Ответить с ИИ»: вопросы входящего письма уходят в документацию проекта, из ответов собирается черновик.

    Письмо не отправляется: черновик попадает в окно ответа, и отправляет его сам пользователь кнопкой «Отправить»."""
    pid = await current_project(session, user, p)
    results: list[QuestionResult] = []
    # Each question goes on its own, with the subject only: the rest of the letter holds the other questions, and
    # with them in the context the search could answer a neighbouring question instead of this one.
    for question in extract_questions(body.letter.strip()):
        r = await p.ask(pid, external_id(user.id), _with_context(question, body.subject, ""), channel="mail-reply")
        results.append(_result(question, r))
    draft, todo = build_reply([(r.question, r.action, r.answer) for r in results])
    return ReplyDraftResponse(project_id=pid, draft=draft, results=results, todo=todo)
