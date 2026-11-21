import { FolderSearch } from 'lucide-react';
import { type ReactNode } from 'react';

import styles from './EmptyState.module.css';

interface EmptyStateProps {
  title: string;
  text?: ReactNode;
  icon?: ReactNode;
}

export const EmptyState = ({ title, text, icon }: EmptyStateProps) => (
  <div className={styles.emptyState}>
    <span className={styles.icon}>{icon ?? <FolderSearch size={44} strokeWidth={1.5} />}</span>
    <p className={styles.title}>{title}</p>
    {text ? <p className={styles.text}>{text}</p> : null}
  </div>
);
