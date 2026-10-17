import { CircleAlert, ExternalLink, RefreshCw, X } from 'lucide-react';

import { ApprovalStatus } from '@/entities/document';
import { type DraftAttachment } from '@/entities/draft';
import { Button, FileTypeIcon } from '@/shared/ui';

import styles from './AttachmentCard.module.css';

interface AttachmentCardProps {
  attachment: DraftAttachment;
  onOpen: () => void;
  onReplace: () => void;
  onExclude: () => void;
  onShowRule: () => void;
}

/** Предложенный файл: название, источник, статус и действия открыть / заменить / исключить. */
export const AttachmentCard = ({
  attachment,
  onOpen,
  onReplace,
  onExclude,
  onShowRule,
}: AttachmentCardProps) => {
  if (attachment.blocked) {
    return (
      <div className={styles.blocked} role="alert">
        <FileTypeIcon type={attachment.fileType} size="lg" />
        <div className={styles.info}>
          <p className={styles.name}>{attachment.name}</p>
          <p className={styles.meta}>
            {attachment.sizeLabel} • {attachment.source} • Файл не прикреплён • передача запрещена
          </p>
          <p className={styles.blockedTitle}>
            <CircleAlert size={18} />
            Вложение заблокировано.
          </p>
          <p className={styles.meta}>{attachment.blockReason}</p>
        </div>
        <div className={styles.blockedActions}>
          <Button onClick={onExclude}>Исключить файл</Button>
          <Button variant="link" onClick={onShowRule}>
            Подробнее о правиле
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.card}>
      <FileTypeIcon type={attachment.fileType} size="lg" />
      <div className={styles.info}>
        <p className={styles.name}>{attachment.name}</p>
        <p className={styles.meta}>
          {attachment.sizeLabel} · {attachment.source}
        </p>
        <ApprovalStatus approval={attachment.approval} text={attachment.approvalNote} />
      </div>
      <div className={styles.actions}>
        <Button size="sm" icon={<ExternalLink size={16} />} onClick={onOpen}>
          Открыть
        </Button>
        <Button size="sm" icon={<RefreshCw size={16} />} onClick={onReplace}>
          Заменить
        </Button>
        <Button size="sm" variant="danger" icon={<X size={16} />} onClick={onExclude}>
          Исключить
        </Button>
      </div>
    </div>
  );
};
