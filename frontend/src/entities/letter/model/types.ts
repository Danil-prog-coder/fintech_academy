export interface Contact {
  name: string;
  email: string;
  initials: string;
  /** Адресат вне домена компании. */
  external?: boolean;
}

export interface Letter {
  id: string;
  from: Contact;
  to: Contact[];
  subject: string;
  preview: string;
  /** Короткая дата для списка: «10:24», «Вчера», «9 окт.». */
  dateLabel: string;
  /** Дата в заголовке письма: «Сегодня, 10:24». */
  fullDateLabel: string;
  hasAttachment: boolean;
  unread: boolean;
  /** Абзацы тела письма. */
  body: string[];
  signature: string[];
}

export type LetterFolder =
  'inbox' | 'starred' | 'snoozed' | 'sent' | 'drafts' | 'archive' | 'trash';

export type LetterFilter = 'all' | 'unread' | 'attachments';
