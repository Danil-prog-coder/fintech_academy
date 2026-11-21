import { CircleAlert, CircleCheck, Info, TriangleAlert } from 'lucide-react';
import { type ReactNode } from 'react';

import { cx } from '@/shared/lib/cx';

import styles from './Notice.module.css';

type NoticeTone = 'warning' | 'danger' | 'info' | 'success' | 'neutral' | 'caution';

const defaultIcons: Record<NoticeTone, ReactNode> = {
  warning: <CircleAlert size={22} />,
  caution: <TriangleAlert size={22} />,
  danger: <CircleAlert size={22} />,
  info: <Info size={22} />,
  success: <CircleCheck size={22} />,
  neutral: <Info size={20} />,
};

interface NoticeProps {
  tone?: NoticeTone;
  title?: string;
  icon?: ReactNode;
  children?: ReactNode;
  action?: ReactNode;
  compact?: boolean;
}

export const Notice = ({
  tone = 'info',
  title,
  icon,
  children,
  action,
  compact = false,
}: NoticeProps) => (
  <div
    className={cx(styles.notice, styles[tone], compact && styles.compact)}
    role={tone === 'danger' ? 'alert' : 'status'}
  >
    <span className={styles.icon}>{icon ?? defaultIcons[tone]}</span>
    <div className={styles.content}>
      {title ? <p className={styles.title}>{title}</p> : null}
      {children ? <div className={styles.text}>{children}</div> : null}
      {action ? <div className={styles.action}>{action}</div> : null}
    </div>
  </div>
);
