import { CircleX } from 'lucide-react';
import { type ReactNode } from 'react';

import { Avatar, Badge } from '@/shared/ui';

import styles from './LetterContent.module.css';
import { type Letter } from '../../model/types';

interface LetterContentProps {
  letter: Letter;
  /** Кнопки действий в шапке письма (звезда, ответ, меню). */
  actions?: ReactNode;
}

export const LetterContent = ({ letter, actions }: LetterContentProps) => (
  <article className={styles.letter}>
    <h1 className={styles.subject}>{letter.subject}</h1>
    <header className={styles.header}>
      <Avatar initials={letter.from.initials} size="lg" />
      <div className={styles.meta}>
        <p className={styles.from}>
          <span className={styles.fromName}>{letter.from.name}</span>{' '}
          <span className={styles.email}>&lt;{letter.from.email}&gt;</span>
          {letter.from.external ? (
            <Badge tone="danger" icon={<CircleX size={14} />}>
              Внешний адресат
            </Badge>
          ) : null}
        </p>
        <p className={styles.to}>Кому: {letter.to.map((item) => item.name).join(', ')}</p>
      </div>
      <span className={styles.date}>{letter.fullDateLabel}</span>
      {actions ? <div className={styles.actions}>{actions}</div> : null}
    </header>
    <div className={styles.body}>
      {letter.body.map((paragraph) => (
        <p key={paragraph} className={styles.paragraph}>
          {paragraph}
        </p>
      ))}
    </div>
    <div className={styles.signature}>
      {letter.signature.map((line) => (
        <span key={line}>{line}</span>
      ))}
    </div>
  </article>
);
