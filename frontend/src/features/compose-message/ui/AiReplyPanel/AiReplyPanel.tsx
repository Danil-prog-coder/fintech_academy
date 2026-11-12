import { Sparkles, Undo2 } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-router';

import {
  describeAskError,
  FeedbackButtons,
  SourceList,
  useDraftReplyMutation,
  type AskErrorInfo,
  type ReplyDraftResponse,
} from '@/entities/qa';
import { routePaths } from '@/shared/config';
import { Button, Notice } from '@/shared/ui';

import styles from './AiReplyPanel.module.css';
import { type ComposeInit } from '../../model/composeSlice';

interface AiReplyPanelProps {
  body: string;
  onBodyChange: (body: string) => void;
  subject: string;
  thread: ComposeInit['thread'];
  /** Цитата исходного письма, которую окно ответа добавило в конец текста. */
  quote: string;
}

/** Поле ввода хранит переводы строк как \n, а в тексте письма бывают \r\n. */
const normalizeBreaks = (text: string) => text.replace(/\r\n?/g, '\n');

/** Делит текст письма на написанное пользователем и цитату исходного письма. */
const splitBody = (rawBody: string, rawQuote: string) => {
  const body = normalizeBreaks(rawBody);
  const quote = normalizeBreaks(rawQuote);
  const at = quote ? body.lastIndexOf(quote) : -1;
  return at === -1 ? { own: body, tail: '' } : { own: body.slice(0, at), tail: body.slice(at) };
};

const withoutQuotes = (text: string) =>
  text
    .split('\n')
    .filter((line) => !line.startsWith('>'))
    .join('\n')
    .trim();

/** «Ответ с ИИ»: черновик ответа на письмо одним нажатием. Цитата исходного письма остаётся. */
export const AiReplyPanel = ({ body, onBodyChange, subject, thread, quote }: AiReplyPanelProps) => {
  const [draftReply, { isLoading }] = useDraftReplyMutation();
  const [result, setResult] = useState<ReplyDraftResponse | null>(null);
  const [previous, setPrevious] = useState<string | null>(null);
  const [failure, setFailure] = useState<AskErrorInfo | null>(null);

  const run = async () => {
    setFailure(null);
    const { own, tail } = splitBody(body, quote);
    const notes = withoutQuotes(own);
    try {
      const reply = await draftReply({
        thread: thread.map((item) => ({
          author: item.author ?? undefined,
          text: item.text,
          sent_at: item.sentAt ?? undefined,
        })),
        subject: subject.trim() || undefined,
        notes: notes || undefined,
      }).unwrap();
      setPrevious(body);
      setResult(reply);
      onBodyChange(tail ? `${reply.draft}\n\n${tail.trimStart()}` : reply.draft);
    } catch (cause) {
      setFailure(describeAskError(cause));
    }
  };

  const undo = () => {
    if (previous !== null) {
      onBodyChange(previous);
    }
    setPrevious(null);
    setResult(null);
  };

  return (
    <section className={styles.panel} aria-label="Ответ с ИИ">
      <Button
        variant="soft"
        size="sm"
        icon={<Sparkles size={16} />}
        disabled={isLoading}
        onClick={() => void run()}
      >
        {isLoading ? 'Пишем черновик…' : result ? 'Написать заново' : 'Ответ с ИИ'}
      </Button>
      {failure ? (
        <Notice tone="danger" compact>
          {failure.message}
        </Notice>
      ) : null}
      {result ? (
        <div className={styles.result}>
          <Notice
            tone={result.todo.length > 0 ? 'warning' : 'success'}
            compact
            action={
              previous !== null ? (
                <Button variant="link" size="sm" icon={<Undo2 size={16} />} onClick={undo}>
                  Вернуть как было
                </Button>
              ) : undefined
            }
          >
            Черновик вставлен в письмо. Проверьте его перед отправкой.
          </Notice>
          {result.todo.length > 0 ? (
            <div className={styles.todo}>
              <p className={styles.caption}>В проекте не нашлось, уточните сами:</p>
              <ul className={styles.list}>
                {result.todo.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
          ) : null}
          {result.used_project ? null : (
            <Notice
              tone="neutral"
              compact
              action={<Link to={routePaths.repo}>Перейти к репозиторию</Link>}
            >
              Репозиторий не подключён или индекс ещё не готов: черновик написан только по
              переписке.
            </Notice>
          )}
          <SourceList sources={result.sources} />
          <FeedbackButtons target={{ question_log_id: result.question_log_id }} />
        </div>
      ) : null}
    </section>
  );
};
