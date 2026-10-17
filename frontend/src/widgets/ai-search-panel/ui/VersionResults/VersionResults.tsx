import { Info, MessageSquare } from 'lucide-react';

import { ApprovalStatus, type DocumentFile } from '@/entities/document';
import { type RankedDocument } from '@/features/ai-search';
import { cx } from '@/shared/lib/cx';
import { showToast } from '@/shared/lib/toast';
import { Badge, Button, FileTypeIcon } from '@/shared/ui';

import styles from './VersionResults.module.css';

interface VersionResultsProps {
  items: RankedDocument[];
  note: string;
  onAttach: (document: DocumentFile) => void;
  onClarify: (document: DocumentFile) => void;
}

/** Несколько подходящих файлов: рекомендуемая версия и альтернативы с причинами. */
export const VersionResults = ({ items, note, onAttach, onClarify }: VersionResultsProps) => (
  <div className={styles.results}>
    <p className={styles.heading}>
      Найдено {items.length} {items.length === 1 ? 'подходящий файл' : 'подходящих файла'}
    </p>
    {items.map(({ document, recommended, explanation }) => (
      <article key={document.id} className={cx(styles.card, recommended && styles.recommended)}>
        <header className={styles.header}>
          <FileTypeIcon type={document.fileType} size="md" />
          <div className={styles.info}>
            <p className={styles.name}>{document.name}</p>
            <p className={styles.meta}>{document.source}</p>
            <p className={styles.meta}>
              {document.updatedLabel} · {document.sizeLabel}
            </p>
          </div>
          {recommended ? <Badge tone="accent">Рекомендуем</Badge> : null}
        </header>
        {recommended ? (
          <ApprovalStatus approval={document.approval} text={document.approvalNote} />
        ) : (
          <span className={styles.badgeRow}>
            <Badge tone="warning">Согласование не найдено</Badge>
          </span>
        )}
        <p className={styles.explanation}>{explanation}</p>
        <div className={styles.actions}>
          <Button
            variant="primary"
            onClick={() => {
              showToast(`Открываем «${document.name}» с обычной проверкой доступа`);
            }}
          >
            Открыть
          </Button>
          <Button
            variant="soft"
            onClick={() => {
              onAttach(document);
            }}
          >
            Выбрать
          </Button>
          <Button
            icon={<MessageSquare size={16} />}
            onClick={() => {
              onClarify(document);
            }}
          >
            Уточнить
          </Button>
        </div>
      </article>
    ))}
    <p className={styles.note}>
      <Info size={20} />
      {note}
    </p>
  </div>
);
