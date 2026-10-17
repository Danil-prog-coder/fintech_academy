import { cx } from '@/shared/lib/cx';

import styles from './FileTypeIcon.module.css';

export type FileType = 'pptx' | 'xlsx' | 'docx' | 'pdf';

const letters: Record<FileType, string> = {
  pptx: 'P',
  xlsx: 'X',
  docx: 'W',
  pdf: 'PDF',
};

interface FileTypeIconProps {
  type: FileType;
  size?: 'sm' | 'md' | 'lg';
}

export const FileTypeIcon = ({ type, size = 'md' }: FileTypeIconProps) => (
  <span className={cx(styles.icon, styles[type], styles[size])} aria-hidden="true">
    {letters[type]}
  </span>
);
