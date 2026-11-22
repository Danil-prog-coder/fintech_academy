import { useState } from 'react';
import { Link } from 'react-router';

import { ticketStatusLabel, useGetTicketsQuery } from '@/entities/ticket';
import { getErrorMessage } from '@/shared/api';
import { Badge, Card, layout, Notice, Select, Skeleton } from '@/shared/ui';
import { PanelLayout } from '@/widgets/panel-layout';

const filters = [
  { value: 'open', label: 'Открытые' },
  { value: 'waiting', label: 'Ждут специалиста' },
  { value: 'in_progress', label: 'В работе' },
  { value: 'resolved', label: 'Решённые' },
  { value: '', label: 'Все' },
] as const;

export const TicketsPage = () => {
  const [status, setStatus] = useState<(typeof filters)[number]['value']>('open');
  const { data, error, isLoading } = useGetTicketsQuery(status, {
    pollingInterval: 10000,
    skipPollingIfUnfocused: true,
  });
  return (
    <PanelLayout title="Обращения в поддержку">
      <div className={layout.row}>
        <Select label="Показать" value={status} options={filters} onChange={setStatus} />
      </div>
      {isLoading ? <Skeleton height={120} /> : null}
      {error ? <Notice tone="danger">{getErrorMessage(error)}</Notice> : null}
      {data?.escalations.length === 0 ? <p className={layout.muted}>Обращений нет.</p> : null}
      <Card>
        <ul className={layout.list}>
          {data?.escalations.map((t) => (
            <li key={t.key} className={layout.item}>
              <Link to={`/tickets/${t.key}`} className={layout.grow}>
                <strong>{t.key}</strong> — {t.summary}
              </Link>
              <Badge
                tone={
                  t.status === 'waiting'
                    ? 'warning'
                    : t.status === 'resolved' || t.status === 'closed'
                      ? 'success'
                      : 'info'
                }
              >
                {ticketStatusLabel[t.status]}
              </Badge>
              {t.jira_key ? <Badge tone="neutral">Jira {t.jira_key}</Badge> : null}
              <span className={layout.muted}>{new Date(t.created_at).toLocaleString('ru-RU')}</span>
            </li>
          ))}
        </ul>
      </Card>
    </PanelLayout>
  );
};
