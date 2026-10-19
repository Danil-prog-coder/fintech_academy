import { Badge, type BadgeTone } from '@/shared/ui';

import styles from './SourceStatusBadge.module.css';
import { type SourceStatus } from '../../model/types';

const meta: Record<SourceStatus, { tone: BadgeTone; label: string }> = {
  working: { tone: 'success', label: 'Работает' },
  attention: { tone: 'warning', label: 'Требует внимания' },
  no_access: { tone: 'danger', label: 'Нет доступа' },
};

interface SourceStatusBadgeProps {
  status: SourceStatus;
  plain?: boolean;
}

export const SourceStatusBadge = ({ status, plain = false }: SourceStatusBadgeProps) => (
  <span className={styles.root}>
    <Badge tone={meta[status].tone} dot plain={plain}>
      {meta[status].label}
    </Badge>
  </span>
);
