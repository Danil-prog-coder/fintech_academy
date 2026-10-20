export type AnswerStatus = 'answered' | 'partial' | 'not_found' | 'out_of_scope';

export interface Source {
  id: number;
  path: string;
  kind: string;
  commit_sha: string;
  snippet: string;
  url: string;
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

export interface MailAskRequest {
  draft: string;
  subject?: string;
  recipients?: string[];
  thread?: ThreadMessage[];
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
}

export type FeedbackTarget = { message_id: number } | { question_log_id: number };

export type FeedbackRequest = FeedbackTarget & { helpful: boolean; comment?: string };
