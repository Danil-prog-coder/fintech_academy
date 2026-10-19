import { FileText, Search, User, Users } from 'lucide-react';
import { Link } from 'react-router';

import { AuditStatus, formatEventTimeShort, useGetAuditEventsQuery } from '@/entities/audit-event';
import { useGetOverviewStatsQuery } from '@/entities/organization';
import { SourceIcon, SourceStatusBadge, useGetSourcesQuery } from '@/entities/source';
import { routePaths } from '@/shared/config';
import { cx } from '@/shared/lib/cx';
import { Skeleton, StatCard } from '@/shared/ui';
import { AdminCard, AdminLayout } from '@/widgets/admin-layout';

import styles from './OverviewPage.module.css';
import { ActivityChart } from '../ActivityChart/ActivityChart';

const numberFormat = new Intl.NumberFormat('ru-RU');

/** A-01: агрегированная статистика без содержания писем. */
export const OverviewPage = () => {
  const { data: stats } = useGetOverviewStatsQuery(undefined);
  const { data: sources = [] } = useGetSourcesQuery(undefined);
  const { data: events = [] } = useGetAuditEventsQuery(undefined);

  const mailSource = sources.find((source) => source.kind === 'mail');
  const documentSources = sources.filter((source) => source.kind === 'documents');
  const documentsOk = documentSources.every((source) => source.status === 'working');
  const usageSources = sources.filter((source) => source.kind !== 'other');
  const maxUsage = Math.max(1, ...usageSources.map((source) => source.aiActions));

  return (
    <AdminLayout
      title="Обзор"
      subtitle="Использование AI-помощника и состояние подключенных источников."
    >
      <div className={styles.stats}>
        {stats ? (
          <>
            <StatCard
              icon={<Users size={26} />}
              value={numberFormat.format(stats.employees)}
              label="сотрудников"
              trend={stats.trends.employees}
              trendNote="за последние 30 дней"
            />
            <StatCard
              icon={<User size={26} />}
              value={numberFormat.format(stats.active)}
              label="активных"
              trend={stats.trends.active}
              trendNote="за последние 30 дней"
            />
            <StatCard
              icon={<FileText size={26} />}
              value={numberFormat.format(stats.drafts)}
              label="AI-черновика"
              trend={stats.trends.drafts}
              trendNote="за последние 30 дней"
            />
            <StatCard
              icon={<Search size={26} />}
              value={numberFormat.format(stats.searches)}
              label="AI-поисков"
              trend={stats.trends.searches}
              trendNote="за последние 30 дней"
            />
          </>
        ) : (
          [0, 1, 2, 3].map((item) => <Skeleton key={item} height={128} />)
        )}
      </div>

      <AdminCard className={styles.connections}>
        <div className={styles.connectionsGrid}>
          <div>
            <h2 className={styles.blockTitle}>Состояние подключений</h2>
            <div className={styles.connectionCards}>
              <div className={styles.connection}>
                <span className={styles.connectionIcon}>
                  <SourceIcon kind="mail" />
                </span>
                <div>
                  <p className={styles.connectionTitle}>
                    Почта {mailSource ? <SourceStatusBadge status={mailSource.status} /> : null}
                  </p>
                  <p className={styles.muted}>Подключено 126 из 126 сотрудников</p>
                </div>
              </div>
              <div className={styles.connection}>
                <span className={styles.connectionIcon}>
                  <SourceIcon kind="documents" />
                </span>
                <div>
                  <p className={styles.connectionTitle}>
                    Документы <SourceStatusBadge status={documentsOk ? 'working' : 'attention'} />
                  </p>
                  <p className={styles.muted}>Подключено {documentSources.length} источника</p>
                </div>
              </div>
            </div>
          </div>
          <div className={styles.recent}>
            <div className={styles.recentHeader}>
              <h2 className={styles.blockTitleSmall}>Последние события</h2>
              <Link className={styles.link} to={routePaths.adminSecurity}>
                Все события →
              </Link>
            </div>
            <ul className={styles.recentList}>
              {events.slice(0, 3).map((event) => (
                <li key={event.id} className={styles.recentItem}>
                  <span className={styles.time}>{formatEventTimeShort(event.at)}</span>
                  <span
                    className={cx(
                      styles.recentDot,
                      event.status === 'success' ? styles.dotOk : styles.dotFail,
                    )}
                  />
                  {event.title}
                </li>
              ))}
            </ul>
          </div>
        </div>
      </AdminCard>

      <div className={styles.row}>
        <AdminCard
          title="Активность сотрудников"
          link={{ to: routePaths.adminEmployees, label: 'Все сотрудники' }}
        >
          {stats ? <ActivityChart points={stats.activity} /> : <Skeleton height={220} />}
        </AdminCard>
        <AdminCard
          title="Использование по источникам"
          link={{ to: routePaths.adminSources, label: 'Все источники' }}
        >
          <ul className={styles.usage}>
            {usageSources.map((source) => (
              <li key={source.id} className={styles.usageItem}>
                <SourceIcon kind={source.kind} />
                <span className={styles.usageName}>{source.name}</span>
                <span className={styles.bar}>
                  <span
                    className={styles.barFill}
                    // Ширина полосы зависит от данных.
                    style={{ width: `${String((source.aiActions / maxUsage) * 100)}%` }}
                  />
                </span>
                <span className={styles.usageValue}>
                  <strong>{numberFormat.format(source.aiActions)}</strong>
                  <span className={styles.muted}>AI-действий</span>
                </span>
                <SourceStatusBadge status={source.status} />
              </li>
            ))}
          </ul>
        </AdminCard>
      </div>

      <AdminCard
        title="Недавняя активность"
        link={{ to: routePaths.adminSecurity, label: 'Все события' }}
      >
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Время</th>
              <th>Событие</th>
              <th>Сотрудник</th>
              <th>Источник</th>
              <th>Статус</th>
            </tr>
          </thead>
          <tbody>
            {events.slice(0, 5).map((event) => (
              <tr key={event.id}>
                <td>{formatEventTimeShort(event.at)}</td>
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
      </AdminCard>
    </AdminLayout>
  );
};
