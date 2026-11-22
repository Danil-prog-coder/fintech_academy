import { CircleHelp, LifeBuoy, MessagesSquare, ThumbsUp, Timer, Users } from 'lucide-react';
import { useState } from 'react';

import { useGetStatsQuery } from '@/entities/statistic';
import { getErrorMessage } from '@/shared/api';
import { Card, layout, Notice, Select, Skeleton, StatCard } from '@/shared/ui';
import { PanelLayout } from '@/widgets/panel-layout';

import styles from './DashboardPage.module.css';

const periods = [
  { value: '7', label: '7 дней' },
  { value: '30', label: '30 дней' },
  { value: '90', label: '90 дней' },
] as const;

const pct = (v: number | null) => (v === null ? '—' : `${String(Math.round(v * 100))}%`);

export const DashboardPage = () => {
  const [days, setDays] = useState<'7' | '30' | '90'>('7');
  const { data, error, isLoading } = useGetStatsQuery(Number(days));
  const max = Math.max(1, ...(data?.by_day.map((d) => d.total) ?? [1]));

  return (
    <PanelLayout title="Статистика">
      <div className={layout.row}>
        <Select label="Период" value={days} options={periods} onChange={setDays} />
      </div>
      {isLoading ? <Skeleton height={120} /> : null}
      {error ? <Notice tone="danger">{getErrorMessage(error)}</Notice> : null}
      {data ? (
        <>
          <div className={layout.grid}>
            <StatCard
              icon={<MessagesSquare size={20} />}
              value={String(data.questions)}
              label="Вопросов"
            />
            <StatCard
              icon={<ThumbsUp size={20} />}
              value={pct(data.answered_share)}
              label="Ответов по документации"
            />
            <StatCard
              icon={<CircleHelp size={20} />}
              value={String(data.unanswered_pending)}
              label="Ждут ответа админа"
            />
            <StatCard
              icon={<LifeBuoy size={20} />}
              value={String(data.escalations.open)}
              label="Открытых обращений в ТП"
            />
            <StatCard
              icon={<Users size={20} />}
              value={String(data.unique_users)}
              label="Спрашивали людей"
            />
            <StatCard
              icon={<Timer size={20} />}
              value={
                data.latency_ms_p50 === null ? '—' : `${(data.latency_ms_p50 / 1000).toFixed(1)} с`
              }
              label="Время ответа (медиана)"
            />
          </div>
          <Card title="Вопросы по дням">
            {data.by_day.length === 0 ? (
              <p className={layout.muted}>За период вопросов не было.</p>
            ) : null}
            <div className={styles.chart} role="img" aria-label="Число вопросов по дням">
              {data.by_day.map((d) => (
                <div key={d.date} className={styles.col} title={`${d.date}: ${String(d.total)}`}>
                  <div
                    className={styles.bar}
                    style={{ height: `${String(Math.round((d.total / max) * 100))}%` }}
                  />
                  <span className={styles.label}>{d.date.slice(5)}</span>
                </div>
              ))}
            </div>
          </Card>
          <Card title="Оценки и исходы">
            <p>
              👍 {data.ratings.up} · 👎 {data.ratings.down} · из кэша: {data.cache_hits} · исходы:{' '}
              {Object.entries(data.actions)
                .map(([k, v]) => `${k} ${String(v)}`)
                .join(', ') || '—'}
            </p>
          </Card>
          {data.top_unanswered.length > 0 ? (
            <Card title="Чего не хватает в документации">
              <ul className={layout.list}>
                {data.top_unanswered.map((q) => (
                  <li key={q} className={layout.item}>
                    {q}
                  </li>
                ))}
              </ul>
            </Card>
          ) : null}
        </>
      ) : null}
    </PanelLayout>
  );
};
