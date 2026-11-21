import { type AnswerAction, type Recommendation } from '../model/types';

export const actionLabel: Record<AnswerAction, string> = {
  answer: 'Ответ найден',
  clarify: 'Нужно уточнение',
  offer_operator: 'Ответа в документации нет',
  escalate: 'Передано в поддержку',
};

export const recommendationText: Record<Recommendation, string> = {
  answer_found: 'Ответ найден в документации проекта — письмо можно не отправлять.',
  partial: 'Ответ найден частично — возможно, письмо всё же нужно.',
  no_answer: 'Ответа в документации нет — отправьте письмо.',
};
