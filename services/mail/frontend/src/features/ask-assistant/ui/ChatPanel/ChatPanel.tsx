import { LifeBuoy, MessageSquarePlus, Send } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router';

import {
  ActionBadge,
  AnswerImages,
  describeAskError,
  FeedbackButtons,
  SourceList,
  useAskMutation,
  useContactSupportMutation,
  useGetPopularQuery,
  useResetChatMutation,
  type Answer,
  type AskErrorInfo,
} from '@/entities/qa';
import { getErrorMessage } from '@/shared/api';
import { routePaths } from '@/shared/config';
import { Button, EmptyState, Notice, Spinner } from '@/shared/ui';

import styles from './ChatPanel.module.css';

interface Turn {
  id: number;
  question: string;
  answer: Answer | null;
}

const STORAGE_KEY = 'mail.chat';

const loadTurns = (): Turn[] => {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as Turn[]) : [];
  } catch {
    return [];
  }
};

const saveTurns = (turns: Turn[]) => {
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(turns.slice(-30)));
  } catch {
    // без хранилища история не переживёт перезагрузку — не критично
  }
};

/** Чат с ассистентом проекта: память диалога хранит платформа, здесь — только то, что видно на экране. */
export const ChatPanel = () => {
  const [turns, setTurns] = useState<Turn[]>(loadTurns);
  const [question, setQuestion] = useState('');
  const [failure, setFailure] = useState<AskErrorInfo | null>(null);
  const [supportNote, setSupportNote] = useState<string | null>(null);
  const [ask, { isLoading }] = useAskMutation();
  const [reset] = useResetChatMutation();
  const [contact, { isLoading: contacting }] = useContactSupportMutation();
  const popular = useGetPopularQuery(undefined);
  const bottom = useRef<HTMLDivElement>(null);
  const nextId = useRef(0);

  useEffect(() => {
    saveTurns(turns);
    bottom.current?.scrollIntoView({ block: 'end' });
  }, [turns]);

  const submit = async (text: string) => {
    const q = text.trim();
    if (!q || isLoading) {
      return;
    }
    setFailure(null);
    setSupportNote(null);
    nextId.current += 1;
    const id = (turns.at(-1)?.id ?? 0) + nextId.current;
    setTurns((current) => [...current, { id, question: q, answer: null }]);
    setQuestion('');
    try {
      const answer = await ask({ message: q }).unwrap();
      setTurns((current) => current.map((t) => (t.id === id ? { ...t, answer } : t)));
    } catch (cause) {
      setTurns((current) => current.filter((t) => t.id !== id));
      setFailure(describeAskError(cause));
      setQuestion(q);
    }
  };

  const toSupport = async (turn: Turn) => {
    try {
      const esc = await contact({
        message: turn.question,
        request_id: turn.answer?.request_id,
      }).unwrap();
      setSupportNote(`Обращение ${esc.key} создано. Ответ специалиста придёт в уведомления.`);
    } catch (cause) {
      setSupportNote(getErrorMessage(cause, 'Не удалось связаться с поддержкой.'));
    }
  };

  const newDialog = async () => {
    setTurns([]);
    setFailure(null);
    setSupportNote(null);
    try {
      await reset(undefined).unwrap();
    } catch {
      // память на платформе сбросится при следующем вопросе по таймауту — не критично
    }
  };

  return (
    <section className={styles.chat} aria-label="Чат с ассистентом">
      <div className={styles.toolbar}>
        <Button
          size="sm"
          icon={<MessageSquarePlus size={16} />}
          disabled={turns.length === 0 || isLoading}
          onClick={() => void newDialog()}
        >
          Новый диалог
        </Button>
      </div>
      <div className={styles.messages}>
        {turns.length === 0 ? (
          <EmptyState
            title="Задайте вопрос по документации проекта"
            text="Ассистент отвечает только по документации и показывает источники."
          />
        ) : null}
        {turns.length === 0 && popular.data?.questions.length ? (
          <div className={styles.toolbar}>
            {popular.data.questions.map((q) => (
              <Button key={q} size="sm" variant="secondary" onClick={() => void submit(q)}>
                {q}
              </Button>
            ))}
          </div>
        ) : null}
        {turns.map((turn) => (
          <div key={turn.id}>
            <div className={styles.user}>{turn.question}</div>
            {turn.answer ? (
              <article className={styles.assistant}>
                <ActionBadge action={turn.answer.action} />
                <p className={styles.text}>{turn.answer.text}</p>
                <AnswerImages images={turn.answer.images ?? []} />
                <SourceList sources={turn.answer.sources ?? []} />
                {turn.answer.question_id ? (
                  <Notice tone="info" compact>
                    Вопрос передан администраторам проекта — их ответ придёт в уведомления.
                  </Notice>
                ) : null}
                {turn.answer.escalation ? (
                  <Notice tone="info" compact>
                    Обращение {turn.answer.escalation.key} передано в поддержку.
                  </Notice>
                ) : null}
                {turn.answer.action === 'offer_operator' && !turn.answer.escalation ? (
                  <Button
                    size="sm"
                    icon={<LifeBuoy size={14} />}
                    disabled={contacting}
                    onClick={() => void toSupport(turn)}
                  >
                    Связаться с поддержкой
                  </Button>
                ) : null}
                {turn.answer.action === 'answer' ? (
                  <FeedbackButtons requestId={turn.answer.request_id} />
                ) : null}
              </article>
            ) : (
              <div className={styles.assistant}>
                <Spinner size="sm" label="Ассистент отвечает" />
              </div>
            )}
          </div>
        ))}
        <div ref={bottom} />
      </div>
      {supportNote ? <Notice tone="info">{supportNote}</Notice> : null}
      {failure ? (
        <Notice
          tone="danger"
          action={
            failure.needsProject ? (
              <Link to={routePaths.projects}>Перейти к проектам</Link>
            ) : undefined
          }
        >
          {failure.message}
          {failure.retryable ? ' Можно повторить.' : ''}
        </Notice>
      ) : null}
      <form
        className={styles.form}
        onSubmit={(event) => {
          event.preventDefault();
          void submit(question);
        }}
      >
        <textarea
          className={styles.input}
          aria-label="Вопрос"
          placeholder="Например: как оформить командировку? (Enter — отправить, Shift+Enter — перенос)"
          rows={2}
          maxLength={4000}
          value={question}
          onChange={(event) => {
            setQuestion(event.target.value);
          }}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault();
              void submit(question);
            }
          }}
        />
        <Button
          type="submit"
          variant="primary"
          icon={<Send size={18} />}
          disabled={isLoading || !question.trim()}
        >
          Спросить
        </Button>
      </form>
    </section>
  );
};
