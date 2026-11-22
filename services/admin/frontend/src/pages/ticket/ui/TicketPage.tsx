import { BookPlus, Hand, Send } from 'lucide-react';
import { useState } from 'react';
import { useParams } from 'react-router';

import {
  ticketStatusLabel,
  useGetTicketQuery,
  useReplyTicketMutation,
  useSaveTicketToKbMutation,
  useSetTicketStatusMutation,
  useTakeTicketMutation,
  type TicketStatus,
} from '@/entities/ticket';
import { getErrorMessage } from '@/shared/api';
import { Badge, Button, Card, Checkbox, layout, Notice, Select, Skeleton } from '@/shared/ui';
import { PanelLayout } from '@/widgets/panel-layout';

import styles from './TicketPage.module.css';

const statusOptions = (Object.keys(ticketStatusLabel) as TicketStatus[]).map((s) => ({
  value: s,
  label: ticketStatusLabel[s],
}));

export const TicketPage = () => {
  const { key = '' } = useParams();
  const {
    data: t,
    error,
    isLoading,
  } = useGetTicketQuery(key, { pollingInterval: 8000, skipPollingIfUnfocused: true });
  const [take, takeState] = useTakeTicketMutation();
  const [reply, replyState] = useReplyTicketMutation();
  const [setStatus] = useSetTicketStatusMutation();
  const [saveKb, saveState] = useSaveTicketToKbMutation();
  const [text, setText] = useState('');
  const [internal, setInternal] = useState(false);
  const open = t ? !['resolved', 'closed'].includes(t.status) : false;

  return (
    <PanelLayout title={`Обращение ${key}`}>
      {isLoading ? <Skeleton height={160} /> : null}
      {error ? <Notice tone="danger">{getErrorMessage(error)}</Notice> : null}
      {t ? (
        <>
          <Card
            title={t.summary}
            actions={
              <>
                {open && t.status === 'waiting' ? (
                  <Button
                    size="sm"
                    variant="primary"
                    icon={<Hand size={16} />}
                    disabled={takeState.isLoading}
                    onClick={() => void take(t.key)}
                  >
                    Взять в работу
                  </Button>
                ) : null}
                <Select
                  label="Статус"
                  size="sm"
                  value={t.status}
                  options={statusOptions}
                  onChange={(s) => void setStatus({ key: t.key, status: s })}
                />
              </>
            }
          >
            <div className={layout.row}>
              <Badge tone="info">{ticketStatusLabel[t.status]}</Badge>
              <Badge tone="neutral">приоритет: {t.priority}</Badge>
              <span className={layout.muted}>пользователь: {t.external_id}</span>
              {t.jira_key ? <Badge tone="neutral">Jira {t.jira_key}</Badge> : null}
              {t.jira_state === 'failed' ? (
                <Badge tone="danger">Jira: не удалось создать задачу</Badge>
              ) : null}
              {t.user_rating ? (
                <span>
                  {t.user_rating > 0 ? '👍 пользователь доволен' : '👎 пользователь недоволен'}
                </span>
              ) : null}
            </div>
            {t.history.length > 0 ? (
              <details>
                <summary>Диалог с ботом до обращения</summary>
                <ul className={layout.list}>
                  {t.history.map((h, i) => (
                    <li key={`${String(i)}-${h.role}`} className={layout.muted}>
                      <strong>{h.role === 'user' ? 'Пользователь' : 'Бот'}:</strong> {h.text}
                    </li>
                  ))}
                </ul>
              </details>
            ) : null}
          </Card>
          <Card title="Переписка">
            <div className={styles.messages}>
              {t.messages?.map((m) => (
                <div
                  key={m.id}
                  className={
                    m.author === 'user'
                      ? styles.user
                      : m.internal
                        ? styles.internal
                        : styles.support
                  }
                >
                  <span className={layout.muted}>
                    {m.author === 'user' ? 'Пользователь' : (m.author_name ?? 'Поддержка')}
                    {m.internal ? ' · внутренняя заметка' : ''} ·{' '}
                    {new Date(m.created_at).toLocaleString('ru-RU')}
                  </span>
                  <p className={layout.pre}>{m.text}</p>
                </div>
              ))}
            </div>
            {open ? (
              <div className={layout.stack}>
                <textarea
                  className={layout.textarea}
                  aria-label="Ответ"
                  placeholder={
                    internal
                      ? 'Заметка для коллег — пользователь её не увидит'
                      : 'Ответ пользователю'
                  }
                  value={text}
                  onChange={(event) => {
                    setText(event.target.value);
                  }}
                />
                <div className={layout.row}>
                  <Checkbox checked={internal} onChange={setInternal} label="Внутренняя заметка" />
                  <Button
                    variant="primary"
                    size="sm"
                    icon={<Send size={16} />}
                    disabled={replyState.isLoading || !text.trim()}
                    onClick={() =>
                      void reply({ key: t.key, text: text.trim(), internal })
                        .unwrap()
                        .then(() => {
                          setText('');
                        })
                    }
                  >
                    Отправить
                  </Button>
                </div>
                {replyState.error ? (
                  <Notice tone="danger">{getErrorMessage(replyState.error)}</Notice>
                ) : null}
              </div>
            ) : null}
          </Card>
          <Card title="База знаний">
            <p className={layout.muted}>
              Ответ поддержки можно сохранить в документацию: на такой же вопрос бот ответит сам.
            </p>
            <div className={layout.row}>
              <Button
                size="sm"
                icon={<BookPlus size={16} />}
                disabled={saveState.isLoading}
                onClick={() => void saveKb({ key: t.key })}
              >
                Сохранить ответы поддержки в базу
              </Button>
            </div>
            {saveState.isSuccess ? (
              <Notice tone="success" compact>
                Сохранено, база пересобирается.
              </Notice>
            ) : null}
            {saveState.error ? (
              <Notice tone="danger" compact>
                {getErrorMessage(saveState.error)}
              </Notice>
            ) : null}
          </Card>
        </>
      ) : null}
    </PanelLayout>
  );
};
