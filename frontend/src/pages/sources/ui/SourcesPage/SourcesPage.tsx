import { CirclePlus, Info, RefreshCw, Search, Settings } from 'lucide-react';
import { useState } from 'react';

import {
  SourceIcon,
  SourceStatusBadge,
  useCheckSourceMutation,
  useGetSourcesQuery,
  type Source,
} from '@/entities/source';
import { cx } from '@/shared/lib/cx';
import { showToast } from '@/shared/lib/toast';
import { Button, Skeleton, Spinner, TextField } from '@/shared/ui';
import { AdminCard, AdminLayout } from '@/widgets/admin-layout';

import styles from './SourcesPage.module.css';

const FEATURED = ['src-mail', 'src-docs', 'src-extra'];

/** A-03: подключённые источники и разрешённые данные. */
export const SourcesPage = () => {
  const { data: sources = [], isLoading } = useGetSourcesQuery(undefined);
  const [checkSource] = useCheckSourceMutation();
  const [checking, setChecking] = useState<string | null>(null);
  const [search, setSearch] = useState('');

  const check = async (source: Source) => {
    setChecking(source.id);
    try {
      const result = await checkSource(source.id).unwrap();
      showToast(
        result.lastCheckResult === 'Успешно'
          ? `«${source.name}»: подключение работает`
          : `«${source.name}»: не удалось подключиться. Проверьте настройки источника.`,
        result.lastCheckResult === 'Успешно' ? 'success' : 'danger',
      );
    } finally {
      setChecking(null);
    }
  };

  const openSettings = (source: Source) => {
    showToast(`Настройки источника «${source.name}» (демо)`);
  };

  const featured = sources.filter((source) => FEATURED.includes(source.id));
  const query = search.trim().toLowerCase();
  const filtered = sources.filter(
    (source) => !query || [source.name, source.typeLabel].join(' ').toLowerCase().includes(query),
  );

  return (
    <AdminLayout title="Источники" subtitle="Управление подключениями и разрешёнными данными.">
      <div className={styles.cards}>
        {isLoading
          ? [0, 1, 2].map((item) => <Skeleton key={item} height={230} />)
          : featured.map((source) => (
              <article key={source.id} className={styles.card}>
                <header className={styles.cardHeader}>
                  <SourceIcon
                    kind={source.kind}
                    variant="circle"
                    tone={source.status === 'working' ? 'accent' : 'warning'}
                  />
                  <div>
                    <h2 className={styles.cardTitle}>{source.name}</h2>
                    <SourceStatusBadge status={source.status} />
                  </div>
                </header>
                <div className={styles.allowed}>
                  <p className={styles.allowedLabel}>Разрешённые данные:</p>
                  <p className={styles.allowedText}>{source.allowedData}</p>
                </div>
                <div className={styles.cardActions}>
                  <Button
                    size="lg"
                    icon={<Settings size={20} />}
                    onClick={() => {
                      openSettings(source);
                    }}
                  >
                    Настройки
                  </Button>
                  <Button
                    variant="primary"
                    size="lg"
                    icon={checking === source.id ? <Spinner size="sm" /> : <RefreshCw size={20} />}
                    disabled={checking === source.id}
                    onClick={() => {
                      void check(source);
                    }}
                  >
                    Проверить подключение
                  </Button>
                </div>
              </article>
            ))}
      </div>

      <AdminCard
        title="Список источников"
        actions={
          <div className={styles.listActions}>
            <TextField
              label="Поиск по источникам"
              placeholder="Поиск по источникам"
              value={search}
              onChange={setSearch}
              icon={<Search size={18} />}
              clearable
            />
            <Button
              variant="primary"
              icon={<CirclePlus size={20} />}
              onClick={() => {
                showToast(
                  'Новый источник подключает администратор через корпоративный каталог (демо)',
                );
              }}
            >
              Добавить источник
            </Button>
          </div>
        }
      >
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Название</th>
                <th>Тип источника</th>
                <th>Разрешённые данные</th>
                <th>Статус</th>
                <th>Последняя проверка</th>
                <th>Действия</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((source) => (
                <tr key={source.id}>
                  <td>
                    <span className={styles.name}>
                      <SourceIcon kind={source.kind} />
                      {source.name}
                    </span>
                  </td>
                  <td className={styles.muted}>{source.typeLabel}</td>
                  <td className={cx(styles.muted, styles.allowedCell)}>{source.allowedData}</td>
                  <td>
                    <SourceStatusBadge status={source.status} plain />
                  </td>
                  <td>
                    <span className={styles.check}>{source.lastCheckLabel}</span>
                    <span className={styles.muted}>{source.lastCheckResult}</span>
                  </td>
                  <td>
                    <span className={styles.rowActions}>
                      <Button
                        icon={<Settings size={18} />}
                        onClick={() => {
                          openSettings(source);
                        }}
                      >
                        Настройки
                      </Button>
                      <Button
                        icon={
                          checking === source.id ? <Spinner size="sm" /> : <RefreshCw size={18} />
                        }
                        disabled={checking === source.id}
                        onClick={() => {
                          void check(source);
                        }}
                      >
                        Проверить
                      </Button>
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </AdminCard>

      <div className={styles.info}>
        <Info size={28} />
        Настройки AI не расширяют исходные права доступа.
      </div>
    </AdminLayout>
  );
};
