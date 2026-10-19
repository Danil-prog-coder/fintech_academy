import { ChevronDown, ChevronRight, ExternalLink, Folder } from 'lucide-react';
import { type Ref, useState } from 'react';

import { RefineForm } from '@/features/refine-reply';
import { showToast } from '@/shared/lib/toast';
import { IconButton, Notice } from '@/shared/ui';

import styles from './ReviewPanel.module.css';

interface ReviewPanelProps {
  letterId: string;
  /** Нашлись ли подтверждающие источники. */
  generic: boolean;
  refineInputRef: Ref<HTMLInputElement>;
}

const sources = [
  {
    id: 'src-letter',
    title: 'Письмо от 10 октября',
    meta: 'Мария Петрова · подтверждение презентации',
  },
  { id: 'src-file', title: 'Файл из «Общие документы»', meta: 'Презентация_финал.pptx' },
];

/** Краткая проверка готового черновика: предупреждения, источники, уточнение. */
export const ReviewPanel = ({ letterId, generic, refineInputRef }: ReviewPanelProps) => {
  const [sourcesOpen, setSourcesOpen] = useState(false);

  return (
    <div className={styles.panel}>
      {generic ? (
        <Notice tone="warning" title="Подтверждающие материалы не найдены" compact>
          AI не нашёл источников по вопросу письма. Проверьте ответ перед отправкой.
        </Notice>
      ) : (
        <Notice tone="warning" title="Сумма бюджета не подтверждена" compact>
          В исходном письме нет подтверждения согласованной суммы.
        </Notice>
      )}

      {generic ? null : (
        <div className={styles.sources}>
          <button
            type="button"
            className={styles.sourcesToggle}
            aria-expanded={sourcesOpen}
            onClick={() => {
              setSourcesOpen((value) => !value);
            }}
          >
            <Folder size={22} className={styles.folderIcon} />
            <span className={styles.sourcesText}>
              <span className={styles.sourcesTitle}>Источники: {sources.length}</span>
              <span className={styles.sourcesMeta}>Письмо от 10 октября</span>
              <span className={styles.sourcesMeta}>Файл из «Общие документы»</span>
            </span>
            {sourcesOpen ? <ChevronDown size={18} /> : <ChevronRight size={18} />}
          </button>
          {sourcesOpen ? (
            <ul className={styles.sourceList}>
              {sources.map((source) => (
                <li key={source.id} className={styles.sourceItem}>
                  <span>
                    <span className={styles.sourceTitle}>{source.title}</span>
                    <span className={styles.sourcesMeta}>{source.meta}</span>
                  </span>
                  <IconButton
                    size="sm"
                    label={`Открыть: ${source.title}`}
                    icon={<ExternalLink size={16} />}
                    onClick={() => {
                      showToast(`Открываем «${source.title}» с обычной проверкой доступа`);
                    }}
                  />
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      )}

      <RefineForm letterId={letterId} inputRef={refineInputRef} />
    </div>
  );
};
