import { type ReactNode } from 'react';

import styles from './Card.module.css';

interface CardProps {
  title?: string;
  actions?: ReactNode;
  children: ReactNode;
}

/** Белая карточка раздела с заголовком и действиями справа. */
export const Card = ({ title, actions, children }: CardProps) => (
  <section className={styles.card} aria-label={title}>
    {title || actions ? (
      <div className={styles.head}>
        {title ? <h2 className={styles.title}>{title}</h2> : null}
        {actions ? <div className={styles.actions}>{actions}</div> : null}
      </div>
    ) : null}
    {children}
  </section>
);
