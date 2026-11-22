/** Действие, которым платформа завершила ответ. */
export type AnswerAction = 'answer' | 'clarify' | 'offer_operator' | 'escalate';

export interface Source {
  citation_label?: string | null;
  label?: string | null;
  document_title?: string | null;
  section_path?: string | null;
  excerpt?: string | null;
  url?: string | null;
}

export interface AnswerImage {
  id: string;
  url: string;
}

export interface AnswerButton {
  text: string;
  action: string;
}

/** Ответ платформы на вопрос (POST /chat/ask). */
export interface Answer {
  project_id: string;
  request_id: string;
  action: AnswerAction;
  text: string;
  sources?: Source[];
  images?: AnswerImage[];
  buttons?: AnswerButton[];
  confidence_level?: 'high' | 'medium' | 'low' | null;
  /** Вопрос ушёл администраторам проекта: их ответ придёт уведомлением. */
  question_id?: number;
  /** Открыто обращение в поддержку. */
  escalation?: { key: string; status: string };
}

export interface ThreadMessage {
  author?: string;
  text: string;
  sent_at?: string;
}

export interface MailAskRequest {
  draft: string;
  subject?: string;
  recipients?: string[];
  thread?: ThreadMessage[];
}

export type Recommendation = 'answer_found' | 'partial' | 'no_answer';

export interface QuestionResult {
  question: string;
  request_id: string | null;
  action: AnswerAction;
  answer: string;
  sources: Source[];
  confidence_level?: string | null;
}

export interface MailAskResponse {
  project_id: string;
  results: QuestionResult[];
  recommendation: Recommendation;
}

export interface FeedbackRequest {
  request_id: string;
  value: 1 | -1;
}

export interface Escalation {
  key: string;
  status: string;
}

/** «Ответить с ИИ»: входящее письмо, на которое пишем ответ. */
export interface ReplyDraftRequest {
  letter: string;
  subject?: string;
  author?: string;
}

export interface ReplyDraftResponse {
  project_id: string;
  /** Готовый текст ответа; пометки «[уточнить: …]» пользователь дописывает сам. */
  draft: string;
  results: QuestionResult[];
  /** Вопросы письма, ответа на которые в документации нет. */
  todo: string[];
}
