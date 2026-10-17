import { ChevronUp } from 'lucide-react';
import { type ReactNode, type RefObject } from 'react';

import {
  aiReplyReset,
  BUDGET_AMOUNT,
  panelCollapsedChanged,
  prepareReply,
  type LetterAiReply,
} from '@/features/prepare-reply';
import { refineCleared, refineReply, selectRefine } from '@/features/refine-reply';
import { useAppDispatch, useAppSelector } from '@/shared/lib/store';
import { IconButton, Logo, Spinner } from '@/shared/ui';

import styles from './AiCheckPanel.module.css';
import { AiErrorPanel } from '../AiErrorPanel/AiErrorPanel';
import { ConflictPanel } from '../ConflictPanel/ConflictPanel';
import { FactsPanel } from '../FactsPanel/FactsPanel';
import { RefineResultPanel } from '../RefineResultPanel/RefineResultPanel';
import { RequestsPanel } from '../RequestsPanel/RequestsPanel';
import { ReviewPanel } from '../ReviewPanel/ReviewPanel';

interface AiCheckPanelProps {
  letterId: string;
  reply: LetterAiReply;
  editorRef: RefObject<HTMLTextAreaElement | null>;
  refineInputRef: RefObject<HTMLInputElement | null>;
}

/** Правая колонка внутри редактора: краткий статус проверки, источники, уточнение. */
export const AiCheckPanel = ({ letterId, reply, editorRef, refineInputRef }: AiCheckPanelProps) => {
  const dispatch = useAppDispatch();
  const refine = useAppSelector((state) => selectRefine(state, letterId));

  const clarifyBudget = () => {
    void dispatch(refineReply({ letterId, query: 'Уточни сумму бюджета' }));
  };

  let content: ReactNode;
  if (reply.status === 'error') {
    content = (
      <AiErrorPanel
        title="Не удалось подготовить ответ"
        onRetry={() => {
          void dispatch(prepareReply({ letterId }));
        }}
        onContinueManually={() => {
          dispatch(aiReplyReset({ letterId }));
          editorRef.current?.focus();
        }}
      />
    );
  } else if (refine.status === 'loading') {
    content = (
      <div className={styles.loading}>
        <Spinner size="md" label="Изменяем ответ" />
        <span>Изменяем ответ…</span>
        <span className={styles.loadingHint}>Ваши правки в других частях текста сохранятся.</span>
      </div>
    );
  } else if (refine.status === 'error') {
    content = (
      <AiErrorPanel
        title="Не удалось обновить ответ"
        onRetry={() => {
          void dispatch(refineReply({ letterId, query: refine.query }));
        }}
        onContinueManually={() => {
          dispatch(refineCleared({ letterId }));
          editorRef.current?.focus();
        }}
      />
    );
  } else if (refine.status === 'done') {
    content = (
      <RefineResultPanel letterId={letterId} refine={refine} refineInputRef={refineInputRef} />
    );
  } else if (reply.scenario === 'partial') {
    content = (
      <RequestsPanel
        onEditReply={() => {
          editorRef.current?.focus();
        }}
      />
    );
  } else if (reply.scenario === 'facts') {
    content = <FactsPanel amount={BUDGET_AMOUNT} onClarify={clarifyBudget} />;
  } else if (reply.scenario === 'conflict') {
    content = <ConflictPanel onClarify={clarifyBudget} />;
  } else {
    content = (
      <ReviewPanel
        letterId={letterId}
        generic={reply.scenario === 'generic'}
        refineInputRef={refineInputRef}
      />
    );
  }

  const caption = reply.scenario === 'partial' ? 'AI-проверка письма' : 'Проверка ответа';

  return (
    <aside className={styles.panel} aria-label="Проверка ответа SOLUTIONS">
      <header className={styles.header}>
        <Logo size="sm" caption={caption} />
        <IconButton
          size="sm"
          label="Свернуть проверку"
          icon={<ChevronUp size={18} />}
          onClick={() => {
            dispatch(panelCollapsedChanged(true));
          }}
        />
      </header>
      {content}
    </aside>
  );
};
