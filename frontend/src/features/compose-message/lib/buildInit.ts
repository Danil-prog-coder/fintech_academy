import { addressFull, formatFullDate, type Address, type MailMessage } from '@/entities/mailbox';

import { emptyCompose, type ComposeInit } from '../model/composeSlice';

const htmlToText = (html: string) =>
  new DOMParser().parseFromString(html, 'text/html').body.textContent;

const plainText = (message: MailMessage) =>
  (message.text ?? (message.html ? htmlToText(message.html) : '')).trim();

const withPrefix = (prefix: string, subject: string) =>
  new RegExp(`^${prefix}:`, 'i').test(subject.trim())
    ? subject
    : `${prefix}: ${subject || '(без темы)'}`;

const unique = (emails: string[]) => [...new Set(emails)];

const quote = (text: string) =>
  text
    .split('\n')
    .map((line) => `> ${line}`)
    .join('\n');

const referencesOf = (message: MailMessage) =>
  [message.references, message.message_id].filter(Boolean).join(' ') || null;

/** Ответ автору письма или всем участникам переписки. */
export const buildReply = (
  message: MailMessage,
  ownEmail: string,
  replyAll: boolean,
): ComposeInit => {
  const own = ownEmail.toLowerCase();
  const others = (list: Address[]) =>
    list.map((a) => a.email).filter((email) => email.toLowerCase() !== own);
  const author = message.sender ? [message.sender.email] : [];
  const header = `${formatFullDate(message.date)}, ${message.sender ? addressFull(message.sender) : 'отправитель'} написал(а):`;
  return {
    ...emptyCompose,
    to: unique(author).join(', '),
    cc: replyAll
      ? unique(
          others([...message.to, ...message.cc]).filter((email) => !author.includes(email)),
        ).join(', ')
      : '',
    subject: withPrefix('Re', message.subject),
    body: `\n\n${header}\n${quote(plainText(message))}`,
    inReplyTo: message.message_id,
    references: referencesOf(message),
    answered: { folder: message.folder, uid: message.uid },
    thread: [
      {
        author: message.sender ? addressFull(message.sender) : null,
        text: plainText(message).slice(0, 20000),
        sentAt: message.date,
      },
    ],
  };
};

export const buildForward = (message: MailMessage): ComposeInit => {
  const lines = [
    '---------- Пересылаемое письмо ----------',
    `От: ${message.sender ? addressFull(message.sender) : ''}`,
    `Дата: ${formatFullDate(message.date)}`,
    `Тема: ${message.subject}`,
    `Кому: ${message.to.map(addressFull).join(', ')}`,
  ];
  return {
    ...emptyCompose,
    subject: withPrefix('Fwd', message.subject),
    body: `\n\n${lines.join('\n')}\n\n${plainText(message)}`,
  };
};

/** Продолжение редактирования черновика: прежний черновик заменяется новым. */
export const buildDraftEdit = (message: MailMessage): ComposeInit => ({
  ...emptyCompose,
  to: message.to.map((a) => a.email).join(', '),
  cc: message.cc.map((a) => a.email).join(', '),
  subject: message.subject,
  body: plainText(message),
  inReplyTo: message.in_reply_to,
  references: message.references,
  replaces: { folder: message.folder, uid: message.uid },
});
