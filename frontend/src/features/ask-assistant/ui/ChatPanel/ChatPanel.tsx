import { MessageSquarePlus, Send } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router';

import {
  AnswerStatusBadge,
  describeAskError,
  FeedbackButtons,
  SourceList,
  useAskMutation,
  useGetConversationQuery,
  type AskErrorInfo,
} from '@/entities/qa';
import { routePaths } from '@/shared/config';
import { Button, EmptyState, Notice, Spinner } from '@/shared/ui';

import styles from './ChatPanel.module.css';

const STORAGE_KEY = 'fa.conversation_id';

const loadConversationId = (): number | null => {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? Number(raw) : null;
  } catch {
    return null;
  }
};

const saveConversationId = (id: number | null) => {
  try {
    if (id === null) {
      localStorage.removeItem(STORAGE_KEY);
    } else {
      localStorage.setItem(STORAGE_KEY, String(id));
    }
  } catch {
    // Без хранилища диалог не переживёт перезагрузку — это не критично.
  }
};

export const ChatPanel = () => {
  const [conversationId, setConversationId] = useState<number | null>(loadConversationId);
  const [question, setQuestion] = useState('');
  const [pending, setPending] = useState<string | null>(null);
  const [failure, setFailure] = useState<AskErrorInfo | null>(null);
  const [commits, setCommits] = useState<Record<number, string>>({});
  const [ask, { isLoading }] = useAskMutation();
  const {
    data: conversation,
    isFetching,
    refetch,
    error: historyError,
  } = useGetConversationQuery(conversationId ?? 0, { skip: conversationId === null });
  const bottom = useRef<HTMLDivElement>(null);

  // Диалог мог быть удалён на сервере (например, при замене репозитория) — тогда начинаем новый.
  const activeId = historyError ? null : conversationId;

  useEffect(() => {
    bottom.current?.scrollIntoView({ block: 'end' });
  }, [conversation?.messages.length, pending]);

  const submit = async () => {
    const text = question.trim();
    if (!text || isLoading) {
      return;
    }
    setFailure(null);
    setPending(text);
    setQuestion('');
    try {
      const answer = await ask({
        question: text,
        conversation_id: activeId ?? undefined,
      }).unwrap();
      if (answer.index_commit) {
        setCommits((current) => ({ ...current, [answer.message_id]: answer.index_commit ?? '' }));
      }
      if (answer.conversation_id !== activeId) {
        saveConversationId(answer.conversation_id);
        setConversationId(answer.conversation_id);
      } else {
        await refetch();
      }
    } catch (cause) {
      setFailure(describeAskError(cause));
      setQuestion(text);
    } finally {
      setPending(null);
    }
  };

  const messages = conversation?.messages ?? [];
  const empty = messages.length === 0 && pending === null;

  return (
    <section className={styles.chat} aria-label="Чат с ассистентом">
      <div className={styles.toolbar}>
        <Button
          size="sm"
          icon={<MessageSquarePlus size={16} />}
          disabled={activeId === null || isLoading}
          onClick={() => {
            saveConversationId(null);
            setConversationId(null);
            setFailure(null);
          }}
        >
          Новый диалог
        </Button>
      </div>
      <div className={styles.messages}>
        {empty ? (
          <EmptyState
            title="Задайте вопрос о проекте"
            text="Ассистент отвечает по подключённому репозиторию и показывает источники."
          />
        ) : null}
        {messages.map((message) =>
          message.role === 'user' ? (
            <div key={message.id} className={styles.user}>
              {message.text}
            </div>
          ) : (
            <article key={message.id} className={styles.assistant}>
              {message.status ? <AnswerStatusBadge status={message.status} /> : null}
              <p className={styles.text}>{message.text}</p>
              <SourceList sources={message.sources} />
              {commits[message.id] ? (
                <p className={styles.commit}>
                  Индекс на коммите {commits[message.id]?.slice(0, 7)}
                </p>
              ) : null}
              <FeedbackButtons target={{ message_id: message.id }} />
            </article>
          ),
        )}
        {pending ? (
          <>
            <div className={styles.user}>{pending}</div>
            <div className={styles.assistant}>
              <Spinner size="sm" label="Ассистент отвечает" />
            </div>
          </>
        ) : null}
        {isFetching && messages.length === 0 && pending === null ? (
          <Spinner label="Загрузка диалога" />
        ) : null}
        <div ref={bottom} />
      </div>
      {failure ? (
        <Notice
          tone="danger"
          action={
            failure.needsRepo ? <Link to={routePaths.repo}>Перейти к репозиторию</Link> : undefined
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
          void submit();
        }}
      >
        <textarea
          className={styles.input}
          aria-label="Вопрос"
          placeholder="Например: как устроена авторизация? (Enter — отправить, Shift+Enter — перенос)"
          rows={2}
          maxLength={4000}
          value={question}
          onChange={(event) => {
            setQuestion(event.target.value);
          }}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault();
              void submit();
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
