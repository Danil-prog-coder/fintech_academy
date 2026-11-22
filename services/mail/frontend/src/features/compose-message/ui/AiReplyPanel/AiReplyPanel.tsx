import { Sparkles, Undo2 } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-router';

import {
  ActionBadge,
  describeAskError,
  FeedbackButtons,
  SourceList,
  useReplyDraftMutation,
  type AskErrorInfo,
  type ReplyDraftResponse,
} from '@/entities/qa';
import { routePaths } from '@/shared/config';
import { Button, Notice } from '@/shared/ui';

import styles from './AiReplyPanel.module.css';

export interface ReplyLetter {
  text: string;
  author: string | null;
  subject: string;
}

interface AiReplyPanelProps {
  letter: ReplyLetter;
  /** Черновик, который уже вставлен в письмо при открытии окна (кнопка «Ответить с ИИ» у письма). */
  initial: ReplyDraftResponse | null;
  /** Вставить новый черновик вместо прежнего (`null` — убрать черновик из письма). */
  onDraft: (draft: string | null) => void;
}

/**
 * «Ответ с ИИ»: вопросы входящего письма ищутся в документации проекта, ответ вставляется в начало письма.
 * Письмо не отправляется само — пользователь проверяет текст и нажимает «Отправить».
 */
export const AiReplyPanel = ({ letter, initial, onDraft }: AiReplyPanelProps) => {
  const [replyDraft, { isLoading }] = useReplyDraftMutation();
  const [result, setResult] = useState<ReplyDraftResponse | null>(initial);
  const [inserted, setInserted] = useState(initial !== null);
  const [failure, setFailure] = useState<AskErrorInfo | null>(null);

  const run = async () => {
    setFailure(null);
    try {
      const response = await replyDraft({
        letter: letter.text,
        subject: letter.subject.trim() || undefined,
        author: letter.author ?? undefined,
      }).unwrap();
      setResult(response);
      setInserted(true);
      onDraft(response.draft);
    } catch (cause) {
      setFailure(describeAskError(cause));
    }
  };

  return (
    <section className={styles.panel} aria-label="Ответ с ИИ">
      <div className={styles.actions}>
        <Button
          variant="soft"
          size="sm"
          icon={<Sparkles size={16} />}
          disabled={isLoading || !letter.text.trim()}
          onClick={() => void run()}
        >
          {isLoading
            ? 'ИИ пишет ответ по документации…'
            : result
              ? 'Написать ответ заново'
              : 'Ответ с ИИ'}
        </Button>
        {result && inserted ? (
          <Button
            variant="ghost"
            size="sm"
            icon={<Undo2 size={16} />}
            disabled={isLoading}
            onClick={() => {
              onDraft(null);
              setInserted(false);
            }}
          >
            Убрать черновик ИИ
          </Button>
        ) : null}
      </div>
      {failure ? (
        <Notice
          tone="danger"
          compact
          action={
            failure.needsProject ? (
              <Link to={routePaths.projects}>Перейти к проектам</Link>
            ) : undefined
          }
        >
          {failure.message}
        </Notice>
      ) : null}
      {result && inserted ? (
        result.todo.length === 0 ? (
          <Notice tone="success" compact>
            Черновик ответа по документации проекта вставлен в письмо. Проверьте текст и нажмите
            «Отправить» — без этого письмо не уйдёт.
          </Notice>
        ) : (
          <Notice tone="warning" compact title="Не на всё нашёлся ответ в документации">
            Замените пометки «[уточнить: …]» в тексте сами, затем нажмите «Отправить»:
            <ul className={styles.todo}>
              {result.todo.map((question) => (
                <li key={question}>{question}</li>
              ))}
            </ul>
          </Notice>
        )
      ) : null}
      {result && inserted && result.results.some((item) => item.sources.length > 0) ? (
        <details className={styles.details}>
          <summary>Источники ответа и оценка</summary>
          {result.results.map((item) => (
            <article key={`${item.question}-${item.request_id ?? ''}`} className={styles.item}>
              <h4 className={styles.question}>{item.question}</h4>
              <ActionBadge action={item.action} />
              <SourceList sources={item.sources} />
              {item.request_id ? <FeedbackButtons requestId={item.request_id} /> : null}
            </article>
          ))}
        </details>
      ) : null}
    </section>
  );
};
