"""Questions the documentation did not answer → the project's owner and admins (from Innopolis: «вопрос уходит админу»).

A question lands here when the agent found no support in the documentation, or when the user disliked an answer.
An admin answers on the site: the answer goes to the user through the integration (`question.answered` event) and,
if asked, is saved into the knowledge base — next time the bot answers by itself.
"""

from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.errors import bad_request, conflict, forbidden, not_found
from ..core.runtime import Core
from ..db.models import Member, Project, Question, QuestionStatus, Role
from ..db.session import utc_now
from . import events
from .rag import RagError, RagUnavailable

log = logging.getLogger(__name__)


def view(q: Question) -> dict:
    return {"id": q.id, "external_id": q.external_id, "text": q.text, "origin": q.origin, "status": q.status,
            "answer": q.answer, "saved_to_kb": q.saved_to_kb, "request_id": q.request_id,
            "created_at": q.created_at.isoformat(), "answered_at": q.answered_at.isoformat() if q.answered_at else None}


async def add(session: AsyncSession, project: Project, member: Member | None, external_id: str, text: str,
              request_id: str | None, origin: str) -> Question | None:
    """Idempotent by request_id: one answer turns into at most one question."""
    if request_id and await session.scalar(select(Question.id).where(Question.request_id == request_id)):
        return None
    q = Question(project_id=project.id, member_id=member.id if member else None, external_id=external_id,
                 request_id=request_id, text=text[:4000], origin=origin)
    session.add(q)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        return None
    return q


async def list_(session: AsyncSession, project: Project, status: str | None, limit: int, offset: int) -> tuple[list[Question], int]:
    q = select(Question).where(Question.project_id == project.id)
    c = select(func.count()).select_from(Question).where(Question.project_id == project.id)
    if status:
        q, c = q.where(Question.status == status), c.where(Question.status == status)
    rows = (await session.scalars(q.order_by(Question.id.desc()).limit(limit).offset(offset))).all()
    return list(rows), int(await session.scalar(c) or 0)


async def _get(session: AsyncSession, project: Project, qid: int) -> Question:
    q = await session.get(Question, qid)
    if q is None or q.project_id != project.id:
        raise not_found("question_not_found", "Вопрос не найден")
    return q


def _require_manager(actor: Member) -> None:
    if not Role(actor.role).is_manager:
        raise forbidden("not_a_manager", "Отвечать на вопросы могут владелец и админы")


async def answer(core: Core, session: AsyncSession, project: Project, actor: Member, qid: int, text: str,
                 save_to_kb: bool, section: str | None) -> Question:
    _require_manager(actor)
    q = await _get(session, project, qid)
    if q.status != QuestionStatus.PENDING:
        raise conflict("already_handled", "На этот вопрос уже ответили или его закрыли")
    text = (text or "").strip()
    if len(text) < 3:
        raise bad_request("empty_answer", "Ответ слишком короткий")
    q.status, q.answer, q.answered_by_member_id, q.answered_at = QuestionStatus.ANSWERED, text[:20000], actor.id, utc_now()
    events.emit(session, project.integration_id, project.public_id, "question.answered",
                {"question_id": q.id, "external_id": q.external_id, "question": q.text, "answer": q.answer,
                 "request_id": q.request_id})
    await session.commit()
    if save_to_kb:
        try:
            await core.rag.knowledge(project.rag_project_id, q.text, q.answer, actor.display_name, section)
            q.saved_to_kb = True
            await session.commit()
        except (RagError, RagUnavailable) as e:
            log.warning("question %s: saving to the knowledge base failed: %s", q.id, e)
    return q


async def dismiss(session: AsyncSession, project: Project, actor: Member, qid: int) -> Question:
    _require_manager(actor)
    q = await _get(session, project, qid)
    if q.status != QuestionStatus.PENDING:
        raise conflict("already_handled", "На этот вопрос уже ответили или его закрыли")
    q.status = QuestionStatus.DISMISSED
    await session.commit()
    return q
