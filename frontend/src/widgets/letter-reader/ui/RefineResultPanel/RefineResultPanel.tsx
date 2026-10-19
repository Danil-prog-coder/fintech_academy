import { RefreshCw, Undo2 } from 'lucide-react';
import { type RefObject } from 'react';

import { RefineForm, undoRefine, type LetterRefine } from '@/features/refine-reply';
import { useAppDispatch } from '@/shared/lib/store';
import { Button, Notice } from '@/shared/ui';

import styles from './RefineResultPanel.module.css';

interface RefineResultPanelProps {
  letterId: string;
  refine: LetterRefine;
  refineInputRef: RefObject<HTMLInputElement | null>;
}

/** Результат точечного уточнения с возможностью отменить последнее AI-изменение. */
export const RefineResultPanel = ({ letterId, refine, refineInputRef }: RefineResultPanelProps) => {
  const dispatch = useAppDispatch();

  return (
    <div className={styles.panel}>
      <Notice tone={refine.changed ? 'success' : 'info'} title={refine.resultTitle} compact>
        {refine.resultDescription}
      </Notice>
      <div className={styles.actions}>
        <Button
          variant="primary"
          icon={<RefreshCw size={18} />}
          onClick={() => {
            refineInputRef.current?.focus();
          }}
        >
          Изменить
        </Button>
        <Button
          variant="soft"
          icon={<Undo2 size={18} />}
          disabled={refine.previousText === null}
          onClick={() => {
            void dispatch(undoRefine({ letterId }));
          }}
        >
          Отменить последнее AI-изменение
        </Button>
      </div>
      <p className={styles.label}>Что изменить в ответе?</p>
      <RefineForm letterId={letterId} initialQuery={refine.query} inputRef={refineInputRef} />
    </div>
  );
};
