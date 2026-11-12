export type AnswerStatus = 'answered' | 'partial' | 'not_found' | 'out_of_scope';

export interface Source {
  /** null у вложений письма: их нет в индексе. */
  id: number | null;
  /** Путь в репозитории или имя вложения. */
  path: string;
  /** code | doc | issue | pr | attachment */
  kind: string;
  commit_sha: string | null;
  snippet: string;
  url: string | null;
}

export interface AskRequest {
  question: string;
  conversation_id?: number;
}

export interface AnswerResponse {
  conversation_id: number;
  message_id: number;
  answer: string;
  status: AnswerStatus;
  sources: Source[];
  index_commit: string | null;
  provider: string | null;
}

export interface ChatMessage {
  id: number;
  role: 'user' | 'assistant';
  text: string;
  sources: Source[];
  status: AnswerStatus | null;
  created_at: string;
}

export interface Conversation {
  id: number;
  created_at: string;
  messages: ChatMessage[];
}

export interface ThreadMessage {
  author?: string;
  text: string;
  sent_at?: string;
}

/** Файл черновика, текст которого ИИ учитывает при ответе (txt/код, PDF, DOCX). */
export interface DraftAttachment {
  filename: string;
  content_type?: string;
  content_base64: string;
}

export interface MailAskRequest {
  draft: string;
  subject?: string;
  recipients?: string[];
  thread?: ThreadMessage[];
  attachments?: DraftAttachment[];
}

export type AttachmentStatus = 'read' | 'unsupported' | 'too_large' | 'empty' | 'unreadable';

/** Что ИИ удалось взять из вложения. */
export interface AttachmentInfo {
  filename: string;
  status: AttachmentStatus;
  chars: number;
  truncated: boolean;
  message: string | null;
}

export type Recommendation = 'answer_found' | 'partial' | 'no_answer' | 'out_of_scope';

export interface QuestionResult {
  question_log_id: number;
  question: string;
  answer: string;
  status: AnswerStatus;
  sources: Source[];
}

export interface MailAskResponse {
  results: QuestionResult[];
  recommendation: Recommendation;
  index_commit: string | null;
  provider: string | null;
  attachments: AttachmentInfo[];
}

export interface ReplyDraftRequest {
  /** Переписка; последнее письмо — то, на которое отвечаем. */
  thread: ThreadMessage[];
  subject?: string;
  /** Что пользователь уже написал: ИИ учитывает это как пожелания к ответу. */
  notes?: string;
}

export interface ReplyDraftResponse {
  question_log_id: number;
  draft: string;
  sources: Source[];
  /** Чего ИИ не нашёл в проекте и пометил в тексте «[уточнить: …]». */
  todo: string[];
  used_project: boolean;
  index_commit: string | null;
  provider: string | null;
}

export type FeedbackTarget = { message_id: number } | { question_log_id: number };

export type FeedbackRequest = FeedbackTarget & { helpful: boolean; comment?: string };
