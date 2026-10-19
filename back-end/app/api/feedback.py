from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.errors import AppError
from app.db.models import Conversation, Feedback, Message, QuestionLog, User
from app.db.session import get_session
from app.schemas.common import ERROR_RESPONSES
from app.schemas.feedback import FeedbackRequest, FeedbackResponse

router = APIRouter(tags=["feedback"], responses=ERROR_RESPONSES)


@router.post("/feedback", response_model=FeedbackResponse, status_code=201)
async def post_feedback(
    body: FeedbackRequest,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    if body.message_id is not None:
        message = await session.get(Message, body.message_id)
        conversation = await session.get(Conversation, message.conversation_id) if message else None
        if message is None or message.role != "assistant" or conversation.user_id != user.id:
            raise AppError("message_not_found", "Сообщение не найдено.", 404)
    else:
        log = await session.get(QuestionLog, body.question_log_id)
        if log is None or log.user_id != user.id:
            raise AppError("question_not_found", "Вопрос не найден.", 404)

    row = Feedback(
        user_id=user.id,
        message_id=body.message_id,
        question_log_id=body.question_log_id,
        helpful=body.helpful,
        comment=body.comment,
    )
    session.add(row)
    await session.commit()
    return FeedbackResponse(id=row.id)
