import { ArrowRight, ExternalLink, Info, Paperclip } from 'lucide-react';
import { useState } from 'react';

import { ApprovalStatus, type DocumentFile } from '@/entities/document';
import { type SearchSource } from '@/features/ai-search';
import { showToast } from '@/shared/lib/toast';
import { Button, DropdownMenu, FileTypeIcon, IconButton } from '@/shared/ui';

import styles from './DocumentResultCard.module.css';
import { SearchSources } from '../SearchSources/SearchSources';

interface DocumentResultCardProps {
  document: DocumentFile;
  reason: string;
  basis: SearchSource[];
  onAttach: (document: DocumentFile) => void;
}

/** Лучший найденный файл и причина выбора. */
export const DocumentResultCard = ({
  document,
  reason,
  basis,
  onAttach,
}: DocumentResultCardProps) => {
  const [basisOpen, setBasisOpen] = useState(false);
  const openDocument = () => {
    showToast(`Открываем «${document.name}» с обычной проверкой доступа`);
  };

  return (
    <div className={styles.result}>
      <article className={styles.card}>
        <header className={styles.header}>
          <FileTypeIcon type={document.fileType} size="lg" />
          <p className={styles.name}>{document.name}</p>
          <DropdownMenu
            label="Действия с документом"
            trigger={<span className={styles.more}>⋯</span>}
            items={[
              {
                id: 'attach',
                label: 'Прикрепить к ответу',
                icon: <Paperclip size={16} />,
                onSelect: () => {
                  onAttach(document);
                },
              },
            ]}
          />
        </header>
        <dl className={styles.meta}>
          <dt>Источник:</dt>
          <dd>{document.source}</dd>
          <dt>Версия:</dt>
          <dd>{document.updatedLabel}</dd>
          <dt>Статус:</dt>
          <dd>
            <ApprovalStatus approval={document.approval} text={document.approvalNote} />
          </dd>
        </dl>
        <div className={styles.actions}>
          <Button variant="primary" size="lg" className={styles.open} onClick={openDocument}>
            Открыть документ
          </Button>
          <IconButton
            variant="outline"
            label="Открыть в новой вкладке"
            icon={<ExternalLink size={20} />}
            className={styles.external}
            onClick={openDocument}
          />
        </div>
      </article>
      <div className={styles.reason}>
        <Info size={20} className={styles.reasonIcon} />
        <div>
          <p>{reason}</p>
          <Button
            variant="link"
            iconAfter={<ArrowRight size={16} />}
            onClick={() => {
              setBasisOpen((value) => !value);
            }}
          >
            {basisOpen ? 'Скрыть основание' : 'Показать основание'}
          </Button>
        </div>
      </div>
      {basisOpen ? <SearchSources sources={basis} /> : null}
    </div>
  );
};
