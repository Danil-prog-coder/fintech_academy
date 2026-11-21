import { RefreshCw, Trash2 } from 'lucide-react';

import { useDeleteFaqMutation, useGetFaqQuery, useRecomputeFaqMutation } from '@/entities/faq';
import { getErrorMessage } from '@/shared/api';
import { Badge, Button, Card, IconButton, layout, Notice, Skeleton } from '@/shared/ui';
import { PanelLayout } from '@/widgets/panel-layout';

/** Кэш частых вопросов: проверенные ответы, которые выдаются без обращения к модели. */
export const FaqPage = () => {
  const { data, error, isLoading } = useGetFaqQuery(undefined);
  const [recompute, recomputeState] = useRecomputeFaqMutation();
  const [remove] = useDeleteFaqMutation();
  return (
    <PanelLayout title="Частые вопросы">
      <Card
        title="Кэш ответов"
        actions={
          <Button
            size="sm"
            icon={<RefreshCw size={16} />}
            disabled={recomputeState.isLoading}
            onClick={() => void recompute(undefined)}
          >
            Пересчитать
          </Button>
        }
      >
        <p className={layout.muted}>
          Самые частые вопросы получают проверенный ответ заранее: похожий вопрос пользователя
          получает его мгновенно. Ответ с тремя 👎 выключается сам.
        </p>
        {recomputeState.isSuccess ? (
          <Notice tone="success" compact>
            Пересчёт запущен.
          </Notice>
        ) : null}
        {isLoading ? <Skeleton height={100} /> : null}
        {error ? <Notice tone="danger">{getErrorMessage(error)}</Notice> : null}
        {data?.entries.length === 0 ? (
          <p className={layout.muted}>Пока пусто: кэш строится по журналу вопросов.</p>
        ) : null}
        <ul className={layout.list}>
          {data?.entries.map((e) => (
            <li key={e.id} className={layout.item}>
              <div className={layout.grow}>
                <strong>{e.question}</strong>
                {e.answer ? <p className={layout.pre}>{e.answer.slice(0, 400)}</p> : null}
                <span className={layout.muted}>
                  выдан {e.served ?? 0} раз · 👍 {e.likes ?? 0} · 👎 {e.dislikes ?? 0}
                </span>
              </div>
              {e.enabled === false ? (
                <Badge tone="neutral">выключен</Badge>
              ) : (
                <Badge tone="success">активен</Badge>
              )}
              <IconButton
                label="Удалить"
                size="sm"
                icon={<Trash2 size={16} />}
                onClick={() => void remove(e.id)}
              />
            </li>
          ))}
        </ul>
      </Card>
    </PanelLayout>
  );
};
