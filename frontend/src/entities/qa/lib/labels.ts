import { type AnswerStatus, type AttachmentStatus, type Recommendation } from '../model/types';

export const attachmentStatusLabel: Record<AttachmentStatus, string> = {
  read: 'Учтено',
  unsupported: 'Формат не читается',
  too_large: 'Слишком большой',
  empty: 'Нет текста',
  unreadable: 'Не удалось прочитать',
};

export const answerStatusLabel: Record<AnswerStatus, string> = {
  answered: 'Ответ найден',
  partial: 'Ответ частичный',
  not_found: 'Ответа в проекте нет',
  out_of_scope: 'Вопрос вне проекта',
};

export const recommendationText: Record<Recommendation, string> = {
  answer_found: 'Ответ найден в проекте — письмо можно не отправлять.',
  partial: 'Ответ найден частично — возможно, письмо всё же нужно.',
  no_answer: 'Ответа в проекте нет — отправьте письмо.',
  out_of_scope: 'Вопросы не относятся к проекту — отправьте письмо.',
};
