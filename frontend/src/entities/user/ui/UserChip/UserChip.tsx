import { ChevronDown } from 'lucide-react';

import { Avatar } from '@/shared/ui';

import styles from './UserChip.module.css';
import { type User } from '../../model/session';

interface UserChipProps {
  user: User;
  tone?: 'neutral' | 'accent';
}

export const UserChip = ({ user, tone = 'neutral' }: UserChipProps) => (
  <span className={styles.chip}>
    <Avatar initials={user.initials} size="md" tone={tone} />
    <span className={styles.text}>
      <span className={styles.name}>{user.name}</span>
      {user.roleLabel ? <span className={styles.role}>{user.roleLabel}</span> : null}
    </span>
    <ChevronDown size={18} className={styles.chevron} />
  </span>
);
