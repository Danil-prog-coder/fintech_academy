import { Check, X } from 'lucide-react';
import { useState } from 'react';

import { useGetSectionsQuery } from '@/entities/document';
import {
  useAnswerQuestionMutation,
  useDismissQuestionMutation,
  useGetQuestionsQuery,
  type Question,
  type QuestionStatus,
} from '@/entities/question';
import { getErrorMessage } from '@/shared/api';
import { Badge, Button, Card, Checkbox, layout, Notice, Select, Skeleton } from '@/shared/ui';
import { PanelLayout } from '@/widgets/panel-layout';

const tabs = [
  { value: 'pending', label: 'Ждут ответа' },
  { value: 'answered', label: 'Отвеченные' },
  { value: 'dismissed', label: 'Закрытые' },
] as const;

const AnswerForm = ({ q }: { q: Question }) => {
  const [text, setText] = useState('');
  const [save, setSave] = useState(true);
  const [section, setSection] = useState('support-answers');
  const { data: sections } = useGetSectionsQuery(undefined);
  const [answer, state] = useAnswerQuestionMutation();
  const [dismiss] = useDismissQuestionMutation();
  const options = [
    { value: 'support-answers', label: 'Ответы на вопросы (по умолчанию)' },
    ...(sections?.sections.map((s) => ({ value: s.slug, label: s.title })) ?? []),
  ];
  return (
    <div className={layout.stack}>
      <textarea
        className={layout.textarea}
        aria-label="Ответ"
        placeholder="Ответ пользователю. Он придёт ему в тот канал, где задан вопрос."
        value={text}
        onChange={(event) => {
          setText(event.target.value);
        }}
      />
      <div className={layout.row}>
        <Checkbox
          checked={save}
          onChange={setSave}
          label="Сохранить в базу знаний — в следующий раз бот ответит сам"
        />
        {save ? (
          <Select
            label="Раздел"
            size="sm"
            value={section}
            options={options}
            onChange={setSection}
          />
        ) : null}
        <Button
          variant="primary"
          size="sm"
          icon={<Check size={16} />}
          disabled={state.isLoading || text.trim().length < 3}
          onClick={() =>
            void answer({
              id: q.id,
              text: text.trim(),
              save_to_kb: save,
              section: section === 'support-answers' ? undefined : section,
            })
          }
        >
          Ответить
        </Button>
        <Button size="sm" variant="ghost" icon={<X size={16} />} onClick={() => void dismiss(q.id)}>
          Закрыть без ответа
        </Button>
      </div>
      {state.error ? <Notice tone="danger">{getErrorMessage(state.error)}</Notice> : null}
    </div>
  );
};

export const QuestionsPage = () => {
  const [status, setStatus] = useState<QuestionStatus>('pending');
  const { data, error, isLoading } = useGetQuestionsQuery(status, {
    pollingInterval: 15000,
    skipPollingIfUnfocused: true,
  });
  return (
    <PanelLayout title="Вопросы без ответа">
      <p className={layout.muted}>
        Сюда попадают вопросы, на которые в документации не нашлось ответа, и ответы, которые
        пользователь отметил «не помогло».
      </p>
      <div className={layout.row}>
        <Select label="Показать" value={status} options={tabs} onChange={setStatus} />
        {data ? <span className={layout.muted}>Всего: {data.total}</span> : null}
      </div>
      {isLoading ? <Skeleton height={100} /> : null}
      {error ? <Notice tone="danger">{getErrorMessage(error)}</Notice> : null}
      {data?.questions.length === 0 ? <p className={layout.muted}>Вопросов нет.</p> : null}
      {data?.questions.map((q) => (
        <Card key={q.id} title={q.text}>
          <div className={layout.row}>
            <Badge tone={q.origin === 'dislike' ? 'warning' : 'neutral'}>
              {q.origin === 'dislike' ? '👎 ответ не помог' : 'нет в документации'}
            </Badge>
            <span className={layout.muted}>
              от {q.external_id} · {new Date(q.created_at).toLocaleString('ru-RU')}
            </span>
            {q.saved_to_kb ? <Badge tone="success">в базе знаний</Badge> : null}
          </div>
          {q.answer ? <p className={layout.pre}>{q.answer}</p> : null}
          {q.status === 'pending' ? <AnswerForm q={q} /> : null}
        </Card>
      ))}
    </PanelLayout>
  );
};
