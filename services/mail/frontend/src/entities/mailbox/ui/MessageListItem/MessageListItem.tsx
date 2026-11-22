import { Paperclip, Star } from 'lucide-react';

import { cx } from '@/shared/lib/cx';
import { Avatar } from '@/shared/ui';

import styles from './MessageListItem.module.css';
import { addressLabel, formatListDate, initialsOf } from '../../lib/format';
import { type MessageSummary } from '../../model/types';

interface MessageListItemProps {
  message: MessageSummary;
  selected: boolean;
  /** В «Отправленных» и «Черновиках» важнее адресат, а не отправитель. */
  showRecipient?: boolean;
  onSelect: (uid: number) => void;
}

export const MessageListItem = ({
  message,
  selected,
  showRecipient = false,
  onSelect,
}: MessageListItemProps) => {
  const person = showRecipient ? (message.to[0] ?? null) : message.sender;
  return (
    <button
      type="button"
      className={cx(styles.item, selected && styles.selected, !message.seen && styles.unread)}
      aria-current={selected ? 'true' : undefined}
      onClick={() => {
        onSelect(message.uid);
      }}
    >
      <Avatar initials={initialsOf(person)} size="md" />
      <span className={styles.content}>
        <span className={styles.top}>
          <span className={styles.from}>{addressLabel(person)}</span>
          <span className={styles.date}>{formatListDate(message.date)}</span>
        </span>
        <span className={styles.subjectRow}>
          <span className={styles.subject}>{message.subject || '(без темы)'}</span>
          {message.flagged ? (
            <Star size={16} className={styles.flag} aria-label="С флажком" />
          ) : null}
          {message.has_attachments ? (
            <Paperclip size={16} className={styles.clip} aria-label="Есть вложение" />
          ) : null}
        </span>
      </span>
    </button>
  );
};
