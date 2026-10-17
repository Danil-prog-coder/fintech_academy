import { ArrowRight } from 'lucide-react';
import { type ReactNode } from 'react';
import { Link } from 'react-router';

import { cx } from '@/shared/lib/cx';

import styles from './AdminCard.module.css';

interface AdminCardProps {
  title?: string;
  description?: string;
  /** Ссылка «Все …» в шапке карточки. */
  link?: { to: string; label: string };
  actions?: ReactNode;
  className?: string;
  children: ReactNode;
}

/** Белая карточка-секция кабинета администратора. */
export const AdminCard = ({
  title,
  description,
  link,
  actions,
  className,
  children,
}: AdminCardProps) => (
  <section className={cx(styles.card, className)}>
    {title || link || actions ? (
      <header className={styles.header}>
        <div className={styles.heading}>
          {title ? <h2 className={styles.title}>{title}</h2> : null}
          {description ? <p className={styles.description}>{description}</p> : null}
        </div>
        {link ? (
          <Link to={link.to} className={styles.link}>
            {link.label} <ArrowRight size={16} />
          </Link>
        ) : null}
        {actions}
      </header>
    ) : null}
    {children}
  </section>
);
