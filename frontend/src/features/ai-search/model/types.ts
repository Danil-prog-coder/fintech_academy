import { type DocumentFile } from '@/entities/document';

export interface SearchRequest {
  query: string;
  /** Предыдущие запросы цепочки уточнений. */
  context: string[];
  /** Номер попытки (повтор поиска при недоступном источнике). */
  attempt: number;
  /** Уникальный ключ запуска — новый поиск всегда выполняется заново. */
  nonce: number;
}

export interface FoundLetter {
  id: string;
  /** Письмо из почтового ящика, если оно доступно для открытия. */
  letterId: string | null;
  subject: string;
  from: string;
  initials: string;
  dateLabel: string;
  snippet: string;
}

export interface SearchSource {
  id: string;
  kind: 'letter' | 'document';
  title: string;
  meta: string;
}

export interface RankedDocument {
  document: DocumentFile;
  recommended: boolean;
  explanation: string;
}

export type SearchResult =
  | { kind: 'document'; document: DocumentFile; reason: string; basis: SearchSource[] }
  | { kind: 'multiple'; items: RankedDocument[]; note: string }
  | { kind: 'answer'; answer: string; sources: SearchSource[] }
  | { kind: 'letters'; letters: FoundLetter[]; unavailableSource: string | null }
  | { kind: 'not_found'; title: string; text: string };
