import { Ban, CircleCheck, Clock, Info } from 'lucide-react';
import { type ReactNode } from 'react';

import { cx } from '@/shared/lib/cx';

import styles from './ApprovalStatus.module.css';
import { type DocumentApproval } from '../../model/types';

const icons: Record<DocumentApproval, ReactNode> = {
  approved: <CircleCheck size={16} />,
  probably_actual: <CircleCheck size={16} />,
  not_found: <Info size={16} />,
  restricted: <Ban size={16} />,
};

const toneClasses: Record<DocumentApproval, string | undefined> = {
  approved: styles.approved,
  probably_actual: styles.probablyActual,
  not_found: styles.notFound,
  restricted: styles.restricted,
};

interface ApprovalStatusProps {
  approval: DocumentApproval;
  text: string;
  /** Иконка часов вместо стандартной — для подписи «Обновлена ...». */
  clock?: boolean;
}

export const ApprovalStatus = ({ approval, text, clock = false }: ApprovalStatusProps) => (
  <span className={cx(styles.status, toneClasses[approval])}>
    {clock ? <Clock size={16} /> : icons[approval]}
    {text}
  </span>
);
