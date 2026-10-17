import { Paperclip } from 'lucide-react';

import { cx } from '@/shared/lib/cx';
import { Avatar } from '@/shared/ui';

import styles from './LetterListItem.module.css';
import { type Letter } from '../../model/types';

interface LetterListItemProps {
  letter: Letter;
  selected: boolean;
  onSelect: (id: string) => void;
}

export const LetterListItem = ({ letter, selected, onSelect }: LetterListItemProps) => (
  <button
    type="button"
    className={cx(styles.item, selected && styles.selected, letter.unread && styles.unread)}
    aria-current={selected ? 'true' : undefined}
    onClick={() => {
      onSelect(letter.id);
    }}
  >
    <Avatar initials={letter.from.initials} size="md" />
    <span className={styles.content}>
      <span className={styles.top}>
        <span className={styles.from}>{letter.from.name}</span>
        <span className={styles.date}>{letter.dateLabel}</span>
      </span>
      <span className={styles.subjectRow}>
        <span className={styles.subject}>{letter.subject}</span>
        {letter.hasAttachment ? (
          <Paperclip size={16} className={styles.clip} aria-label="Есть вложение" />
        ) : null}
      </span>
      <span className={styles.preview}>{letter.preview}</span>
    </span>
  </button>
);
