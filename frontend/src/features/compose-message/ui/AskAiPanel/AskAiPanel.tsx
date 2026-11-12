import { Paperclip, Sparkles } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-router';

import {
  AnswerStatusBadge,
  attachmentStatusLabel,
  describeAskError,
  FeedbackButtons,
  recommendationText,
  SourceList,
  useAskAboutDraftMutation,
  type AskErrorInfo,
  type AttachmentInfo,
  type MailAskResponse,
} from '@/entities/qa';
import { routePaths } from '@/shared/config';
import { Badge, Button, Notice } from '@/shared/ui';

import styles from './AskAiPanel.module.css';
import { AI_MAX_FILES, aiSupport, prepareAiAttachments } from '../../lib/aiAttachments';
import { splitAddresses } from '../../lib/files';
import { type ComposeInit } from '../../model/composeSlice';

interface AskAiPanelProps {
  body: string;
  subject: string;
  recipients: string;
  thread: ComposeInit['thread'];
  /** Вложения письма: их текст ИИ учитывает как контекст. */
  files: File[];
}

/** Цитаты (строки с «>») — это чужой текст, вопросы ищем только в написанном самим пользователем. */
const ownText = (body: string) =>
  body
    .split('\n')
    .filter((line) => !line.startsWith('>'))
    .join('\n')
    .trim();

const formatChars = (chars: number) => `${chars.toLocaleString('ru-RU')} симв.`;

const AttachmentReport = ({ items }: { items: AttachmentInfo[] }) => (
  <section aria-label="Вложения для ИИ" className={styles.attachments}>
    <h4 className={styles.attachmentsTitle}>Вложения</h4>
    <ul className={styles.attachmentList}>
      {items.map((item, index) => (
        <li key={`${item.filename}-${String(index)}`} className={styles.attachment}>
          <Paperclip size={14} />
          <span className={styles.attachmentName}>{item.filename}</span>
          {item.status === 'read' ? (
            <Badge tone={item.truncated ? 'warning' : 'success'}>
              {item.truncated
                ? `Учтено начало · ${formatChars(item.chars)}`
                : `${attachmentStatusLabel.read} · ${formatChars(item.chars)}`}
            </Badge>
          ) : (
            <Badge tone="neutral">{item.message ?? attachmentStatusLabel[item.status]}</Badge>
          )}
        </li>
      ))}
    </ul>
  </section>
);

const recommendationTone = {
  answer_found: 'success',
  partial: 'warning',
  no_answer: 'neutral',
  out_of_scope: 'neutral',
} as const;

/** «Спросить у ИИ»: подсказка по черновику. Письмо не отправляется и не блокируется. */
export const AskAiPanel = ({ body, subject, recipients, thread, files }: AskAiPanelProps) => {
  const [askAboutDraft, { isLoading }] = useAskAboutDraftMutation();
  const [result, setResult] = useState<MailAskResponse | null>(null);
  const [failure, setFailure] = useState<AskErrorInfo | null>(null);
  const [report, setReport] = useState<AttachmentInfo[]>([]);
  const draft = ownText(body);
  const readable = Math.min(files.filter((file) => aiSupport(file) === 'ok').length, AI_MAX_FILES);

  const run = async () => {
    setFailure(null);
    try {
      const { attachments, skipped } = await prepareAiAttachments(files);
      const response = await askAboutDraft({
        draft,
        subject: subject.trim() || undefined,
        recipients: splitAddresses(recipients),
        thread: thread.map((item) => ({
          author: item.author ?? undefined,
          text: item.text,
          sent_at: item.sentAt ?? undefined,
        })),
        attachments,
      }).unwrap();
      setResult(response);
      setReport([...response.attachments, ...skipped]);
    } catch (cause) {
      setResult(null);
      setReport([]);
      setFailure(describeAskError(cause));
    }
  };

  return (
    <section className={styles.panel} aria-label="Спросить у ИИ">
      <Button
        variant="soft"
        size="sm"
        icon={<Sparkles size={16} />}
        disabled={isLoading || !draft}
        onClick={() => void run()}
      >
        {isLoading ? 'Ищем ответ в проекте…' : 'Спросить у ИИ'}
      </Button>
      {readable > 0 && !result ? (
        <p className={styles.hint}>ИИ учтёт текст вложений: {readable}</p>
      ) : null}
      {failure ? (
        <Notice
          tone="danger"
          compact
          action={
            failure.needsRepo ? <Link to={routePaths.repo}>Перейти к репозиторию</Link> : undefined
          }
        >
          {failure.message}
        </Notice>
      ) : null}
      {result ? (
        <div className={styles.result}>
          <Notice tone={recommendationTone[result.recommendation]} compact>
            {recommendationText[result.recommendation]} Письмо можно отправить в любом случае.
          </Notice>
          {report.length > 0 ? <AttachmentReport items={report} /> : null}
          {result.results.length === 0 ? (
            <p className={styles.empty}>В черновике не найдено вопросов.</p>
          ) : null}
          {result.results.map((item) => (
            <article key={item.question_log_id} className={styles.item}>
              <h4 className={styles.question}>{item.question}</h4>
              <AnswerStatusBadge status={item.status} />
              <p className={styles.answer}>{item.answer}</p>
              <SourceList sources={item.sources} />
              <FeedbackButtons target={{ question_log_id: item.question_log_id }} />
            </article>
          ))}
          {result.index_commit ? (
            <p className={styles.commit}>Индекс на коммите {result.index_commit.slice(0, 7)}</p>
          ) : null}
        </div>
      ) : null}
    </section>
  );
};
