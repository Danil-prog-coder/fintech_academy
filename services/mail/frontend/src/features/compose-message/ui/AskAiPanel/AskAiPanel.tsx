import { Sparkles } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-router';

import {
  ActionBadge,
  describeAskError,
  FeedbackButtons,
  recommendationText,
  SourceList,
  useAskAboutDraftMutation,
  type AskErrorInfo,
  type MailAskResponse,
} from '@/entities/qa';
import { routePaths } from '@/shared/config';
import { Button, Notice } from '@/shared/ui';

import styles from './AskAiPanel.module.css';
import { splitAddresses } from '../../lib/files';
import { type ComposeInit } from '../../model/composeSlice';

interface AskAiPanelProps {
  body: string;
  subject: string;
  recipients: string;
  thread: ComposeInit['thread'];
}

/** Цитаты (строки с «>») — это чужой текст, вопросы ищем только в написанном самим пользователем. */
const ownText = (body: string) =>
  body
    .split('\n')
    .filter((line) => !line.startsWith('>'))
    .join('\n')
    .trim();

const recommendationTone = {
  answer_found: 'success',
  partial: 'warning',
  no_answer: 'neutral',
} as const;

/** «Спросить у ИИ»: вопросы из черновика уходят в документацию проекта на платформе. Письмо не блокируется. */
export const AskAiPanel = ({ body, subject, recipients, thread }: AskAiPanelProps) => {
  const [askAboutDraft, { isLoading }] = useAskAboutDraftMutation();
  const [result, setResult] = useState<MailAskResponse | null>(null);
  const [failure, setFailure] = useState<AskErrorInfo | null>(null);
  const draft = ownText(body);

  const run = async () => {
    setFailure(null);
    try {
      const response = await askAboutDraft({
        draft,
        subject: subject.trim() || undefined,
        recipients: splitAddresses(recipients),
        thread: thread.map((item) => ({
          author: item.author ?? undefined,
          text: item.text,
          sent_at: item.sentAt ?? undefined,
        })),
      }).unwrap();
      setResult(response);
    } catch (cause) {
      setResult(null);
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
        {isLoading ? 'Ищем ответ в документации проекта…' : 'Спросить у ИИ'}
      </Button>
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
      {result ? (
        <div className={styles.result}>
          <Notice tone={recommendationTone[result.recommendation]} compact>
            {recommendationText[result.recommendation]} Письмо можно отправить в любом случае.
          </Notice>
          {result.results.map((item) => (
            <article key={`${item.question}-${item.request_id ?? ''}`} className={styles.item}>
              <h4 className={styles.question}>{item.question}</h4>
              <ActionBadge action={item.action} />
              <p className={styles.answer}>{item.answer}</p>
              <SourceList sources={item.sources} />
              {item.request_id ? <FeedbackButtons requestId={item.request_id} /> : null}
            </article>
          ))}
        </div>
      ) : null}
    </section>
  );
};
