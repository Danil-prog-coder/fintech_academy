import { Box, FileText, Mail } from 'lucide-react';

import { cx } from '@/shared/lib/cx';

import styles from './SourceIcon.module.css';
import { type SourceKind } from '../../model/types';

interface SourceIconProps {
  kind: SourceKind;
  variant?: 'plain' | 'circle';
  tone?: 'accent' | 'warning';
}

export const SourceIcon = ({ kind, variant = 'plain', tone = 'accent' }: SourceIconProps) => {
  const size = variant === 'circle' ? 30 : 24;
  const icon =
    kind === 'mail' ? (
      <Mail size={size} />
    ) : kind === 'documents' ? (
      <FileText size={size} />
    ) : (
      <Box size={size} />
    );

  return (
    <span
      className={cx(styles.icon, variant === 'circle' && styles.circle, styles[tone])}
      aria-hidden="true"
    >
      {icon}
    </span>
  );
};
