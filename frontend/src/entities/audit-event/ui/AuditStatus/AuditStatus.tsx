import { cx } from '@/shared/lib/cx';

import styles from './AuditStatus.module.css';
import { auditEventStatusLabels, type AuditEventStatus } from '../../model/types';

interface AuditStatusProps {
  status: AuditEventStatus;
}

export const AuditStatus = ({ status }: AuditStatusProps) => (
  <span className={cx(styles.status, styles[status])}>
    <span className={styles.dot} aria-hidden="true" />
    {auditEventStatusLabels[status]}
  </span>
);
