import { ArrowDownUp, Download, RotateCcw } from 'lucide-react';
import { useState } from 'react';

import {
  auditEventStatusLabels,
  AuditStatus,
  auditEventTypeLabels,
  formatEventTimeFull,
  useGetAuditEventsQuery,
  type AuditEventStatus,
  type AuditEventType,
} from '@/entities/audit-event';
import { downloadCsv } from '@/shared/lib/download';
import { showToast } from '@/shared/lib/toast';
import { Button, Select, type SelectOption } from '@/shared/ui';
import { AdminCard } from '@/widgets/admin-layout';

import styles from './EventJournal.module.css';

type Period = '1' | '7' | '30' | 'all';

const periodOptions: SelectOption<Period>[] = [
  { value: '1', label: 'Последние 24 часа' },
  { value: '7', label: 'Последние 7 дней' },
  { value: '30', label: 'Последние 30 дней' },
  { value: 'all', label: 'За всё время' },
];

const typeOptions: SelectOption<AuditEventType | 'all'>[] = [
  { value: 'all', label: 'Все события' },
  ...Object.entries(auditEventTypeLabels).map(([value, label]) => ({
    value: value as AuditEventType,
    label,
  })),
];

const statusOptions: SelectOption<AuditEventStatus | 'all'>[] = [
  { value: 'all', label: 'Все статусы' },
  ...Object.entries(auditEventStatusLabels).map(([value, label]) => ({
    value: value as AuditEventStatus,
    label,
  })),
];

const DAY = 24 * 60 * 60 * 1000;

/** Журнал разрешённых событий. Содержимое писем не отображается. */
export const EventJournal = () => {
  const { data: events = [] } = useGetAuditEventsQuery(undefined);
  const [period, setPeriod] = useState<Period>('30');
  const [type, setType] = useState<AuditEventType | 'all'>('all');
  const [source, setSource] = useState('all');
  const [employee, setEmployee] = useState('all');
  const [status, setStatus] = useState<AuditEventStatus | 'all'>('all');
  const [ascending, setAscending] = useState(false);
  // Момент открытия журнала — точка отсчёта для фильтра по периоду.
  const [now] = useState(() => Date.now());

  const unique = (values: (string | null)[]) =>
    [...new Set(values.filter((value): value is string => Boolean(value)))].sort();

  const sourceOptions: SelectOption<string>[] = [
    { value: 'all', label: 'Все источники' },
    ...unique(events.map((event) => event.source)).map((value) => ({ value, label: value })),
  ];
  const employeeOptions: SelectOption<string>[] = [
    { value: 'all', label: 'Все сотрудники' },
    ...unique(events.map((event) => event.employee)).map((value) => ({ value, label: value })),
  ];

  const filtered = events
    .filter(
      (event) =>
        (period === 'all' || now - new Date(event.at).getTime() <= Number(period) * DAY) &&
        (type === 'all' || event.type === type) &&
        (source === 'all' || event.source === source) &&
        (employee === 'all' || event.employee === employee) &&
        (status === 'all' || event.status === status),
    )
    .sort((a, b) => (ascending ? 1 : -1) * a.at.localeCompare(b.at));

  const reset = () => {
    setPeriod('30');
    setType('all');
    setSource('all');
    setEmployee('all');
    setStatus('all');
  };

  const exportCsv = () => {
    downloadCsv('journal-sobytiy.csv', [
      ['Время', 'Событие', 'Сотрудник', 'Источник', 'Статус'],
      ...filtered.map((event) => [
        formatEventTimeFull(event.at),
        event.title,
        event.employee ?? '—',
        event.source ?? '—',
        auditEventStatusLabels[event.status],
      ]),
    ]);
    showToast(`Экспортировано событий: ${String(filtered.length)}`, 'success');
  };

  return (
    <AdminCard
      title="Журнал событий"
      description="Записи о действиях в системе. Содержимое писем не отображается."
      actions={
        <Button icon={<Download size={18} />} onClick={exportCsv}>
          Экспорт
        </Button>
      }
    >
      <div className={styles.filters}>
        <label className={styles.filter}>
          <span className={styles.label}>Период</span>
          <Select label="Период" value={period} options={periodOptions} onChange={setPeriod} />
        </label>
        <label className={styles.filter}>
          <span className={styles.label}>Тип события</span>
          <Select label="Тип события" value={type} options={typeOptions} onChange={setType} />
        </label>
        <label className={styles.filter}>
          <span className={styles.label}>Источник</span>
          <Select label="Источник" value={source} options={sourceOptions} onChange={setSource} />
        </label>
        <label className={styles.filter}>
          <span className={styles.label}>Сотрудник</span>
          <Select
            label="Сотрудник"
            value={employee}
            options={employeeOptions}
            onChange={setEmployee}
          />
        </label>
        <label className={styles.filter}>
          <span className={styles.label}>Статус</span>
          <Select label="Статус" value={status} options={statusOptions} onChange={setStatus} />
        </label>
        <Button icon={<RotateCcw size={18} />} onClick={reset}>
          Сбросить
        </Button>
      </div>
      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>
                <button
                  type="button"
                  className={styles.sort}
                  onClick={() => {
                    setAscending((value) => !value);
                  }}
                >
                  Время <ArrowDownUp size={14} />
                </button>
              </th>
              <th>Событие</th>
              <th>Сотрудник</th>
              <th>Источник</th>
              <th>Статус</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((event) => (
              <tr key={event.id}>
                <td className={styles.nowrap}>{formatEventTimeFull(event.at)}</td>
                <td>{event.title}</td>
                <td>{event.employee ?? '—'}</td>
                <td>{event.source ?? '—'}</td>
                <td>
                  <AuditStatus status={event.status} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {filtered.length === 0 ? (
          <p className={styles.empty}>Нет событий по выбранным условиям.</p>
        ) : null}
      </div>
    </AdminCard>
  );
};
