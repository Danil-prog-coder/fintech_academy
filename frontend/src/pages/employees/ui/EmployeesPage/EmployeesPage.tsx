import {
  Ban,
  ChevronLeft,
  ChevronRight,
  Clock,
  EllipsisVertical,
  Info,
  Plus,
  Search,
  ShieldCheck,
  User,
  Users,
} from 'lucide-react';
import { useState } from 'react';

import {
  roleLabels,
  statusLabels,
  useGetEmployeesQuery,
  useGetEmployeeStatsQuery,
  useSetEmployeeAiMutation,
  useSetEmployeeRoleMutation,
  type EmployeeRole,
  type EmployeeStatus,
} from '@/entities/employee';
import { cx } from '@/shared/lib/cx';
import { showToast } from '@/shared/lib/toast';
import {
  Avatar,
  Badge,
  Button,
  Checkbox,
  DropdownMenu,
  Select,
  Skeleton,
  StatCard,
  TextField,
  Toggle,
  type BadgeTone,
  type SelectOption,
} from '@/shared/ui';
import { AdminCard, AdminLayout } from '@/widgets/admin-layout';

import styles from './EmployeesPage.module.css';

const roleOptions: SelectOption<EmployeeRole>[] = [
  { value: 'employee', label: roleLabels.employee },
  { value: 'admin', label: roleLabels.admin },
  { value: 'security', label: roleLabels.security },
];

const roleFilterOptions: SelectOption<EmployeeRole | 'all'>[] = [
  { value: 'all', label: 'Все роли' },
  ...roleOptions,
];

const statusFilterOptions: SelectOption<EmployeeStatus | 'all'>[] = [
  { value: 'all', label: 'Все статусы' },
  { value: 'active', label: statusLabels.active },
  { value: 'pending', label: statusLabels.pending },
  { value: 'disabled', label: statusLabels.disabled },
];

const statusTone: Record<EmployeeStatus, BadgeTone> = {
  active: 'success',
  pending: 'warning',
  disabled: 'neutral',
};

/** A-02: сотрудники и доступ к AI-помощнику. */
export const EmployeesPage = () => {
  const [search, setSearch] = useState('');
  const [role, setRole] = useState<EmployeeRole | 'all'>('all');
  const [status, setStatus] = useState<EmployeeStatus | 'all'>('all');
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<string[]>([]);

  const { data: stats } = useGetEmployeeStatsQuery(undefined);
  const { data, isFetching } = useGetEmployeesQuery({ search, role, status, page });
  const [setEmployeeAi] = useSetEmployeeAiMutation();
  const [setEmployeeRole] = useSetEmployeeRoleMutation();

  const items = data?.items ?? [];
  const allSelected = items.length > 0 && items.every((item) => selected.includes(item.id));

  const changeFilter =
    <T,>(setter: (value: T) => void) =>
    (value: T) => {
      setter(value);
      setPage(1);
      setSelected([]);
    };

  const toggleAi = async (id: string, name: string, enabled: boolean) => {
    await setEmployeeAi({ id, enabled });
    showToast(
      enabled
        ? `AI-помощник включён: ${name}`
        : `AI-помощник отключён: ${name}. Обычная почта работает как прежде.`,
      enabled ? 'success' : 'neutral',
    );
  };

  const bulkAi = async (enabled: boolean) => {
    await Promise.all(selected.map((id) => setEmployeeAi({ id, enabled })));
    showToast(`${enabled ? 'Включён' : 'Отключён'} AI для сотрудников: ${String(selected.length)}`);
    setSelected([]);
  };

  return (
    <AdminLayout title="Сотрудники" subtitle="Управление сотрудниками и доступом к AI-помощнику.">
      <div className={styles.stats}>
        {stats ? (
          <>
            <StatCard
              icon={<Users size={26} />}
              value={String(stats.total)}
              label="всего сотрудников"
              trend="+12%"
              trendNote="за последние 30 дней"
            />
            <StatCard
              icon={<User size={26} />}
              value={String(stats.active)}
              label="активных"
              trend="+8%"
              trendNote="за последние 30 дней"
            />
            <StatCard
              icon={<Clock size={26} />}
              value={String(stats.pending)}
              label="в ожидании"
              trend="+3"
              trendNote="за последние 30 дней"
            />
            <StatCard
              icon={<Ban size={26} />}
              value={String(stats.aiDisabled)}
              label="AI отключён"
              trend="+5"
              trendNote="за последние 30 дней"
            />
          </>
        ) : (
          [0, 1, 2, 3].map((item) => <Skeleton key={item} height={128} />)
        )}
      </div>

      <AdminCard>
        <div className={styles.filters}>
          <TextField
            className={styles.search}
            label="Поиск сотрудников"
            placeholder="Поиск по имени, email или отделу"
            value={search}
            onChange={changeFilter(setSearch)}
            icon={<Search size={20} />}
            clearable
            size="lg"
          />
          <label className={styles.filter}>
            <span className={styles.filterLabel}>Роль</span>
            <Select
              label="Роль"
              value={role}
              options={roleFilterOptions}
              onChange={changeFilter(setRole)}
            />
          </label>
          <label className={styles.filter}>
            <span className={styles.filterLabel}>Статус</span>
            <Select
              label="Статус"
              value={status}
              options={statusFilterOptions}
              onChange={changeFilter(setStatus)}
            />
          </label>
          <span className={styles.found}>
            Найдено: {data?.found ?? '…'} из {data?.total ?? '…'}
          </span>
          <Button
            variant="primary"
            size="lg"
            icon={<Plus size={20} />}
            onClick={() => {
              showToast('Приглашение отправляется через корпоративный каталог (демо)');
            }}
          >
            Пригласить сотрудника
          </Button>
        </div>

        {selected.length > 0 ? (
          <div className={styles.bulk}>
            Выбрано: {selected.length}
            <Button size="sm" onClick={() => void bulkAi(true)}>
              Включить AI
            </Button>
            <Button size="sm" onClick={() => void bulkAi(false)}>
              Отключить AI
            </Button>
          </div>
        ) : null}

        <div className={cx(styles.tableWrap, isFetching && styles.fetching)}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th className={styles.checkCell}>
                  <Checkbox
                    hideLabel
                    label="Выбрать всех на странице"
                    checked={allSelected}
                    onChange={(checked) => {
                      setSelected(checked ? items.map((item) => item.id) : []);
                    }}
                  />
                </th>
                <th>Сотрудник</th>
                <th>Роль</th>
                <th>Статус</th>
                <th>
                  <span
                    className={styles.aiHeader}
                    title="Отключается только AI-помощник. Обычная почта продолжает работать."
                  >
                    AI-помощник <Info size={16} />
                  </span>
                </th>
                <th className={styles.actionsCell}>Действия</th>
              </tr>
            </thead>
            <tbody>
              {items.map((employee) => (
                <tr key={employee.id}>
                  <td className={styles.checkCell}>
                    <Checkbox
                      hideLabel
                      label={`Выбрать ${employee.name}`}
                      checked={selected.includes(employee.id)}
                      onChange={(checked) => {
                        setSelected((value) =>
                          checked
                            ? [...value, employee.id]
                            : value.filter((id) => id !== employee.id),
                        );
                      }}
                    />
                  </td>
                  <td>
                    <span className={styles.person}>
                      <Avatar initials={employee.initials} tone="accent" />
                      <span>
                        <span className={styles.name}>{employee.name}</span>
                        <span className={styles.email}>{employee.email}</span>
                      </span>
                    </span>
                  </td>
                  <td>
                    <Select
                      label={`Роль: ${employee.name}`}
                      value={employee.role}
                      options={roleOptions}
                      onChange={(value) => {
                        void setEmployeeRole({ id: employee.id, role: value }).then(() => {
                          showToast(`Роль обновлена: ${employee.name} — ${roleLabels[value]}`);
                        });
                      }}
                    />
                  </td>
                  <td>
                    <Badge tone={statusTone[employee.status]} dot>
                      {statusLabels[employee.status]}
                    </Badge>
                  </td>
                  <td>
                    <span className={styles.aiCell}>
                      <Toggle
                        label={`AI-помощник: ${employee.name}`}
                        checked={employee.aiEnabled}
                        onChange={(checked) => {
                          void toggleAi(employee.id, employee.name, checked);
                        }}
                      />
                      {employee.aiEnabled ? 'AI включён' : 'AI отключён'}
                    </span>
                  </td>
                  <td className={styles.actionsCell}>
                    <DropdownMenu
                      label={`Действия: ${employee.name}`}
                      trigger={<EllipsisVertical size={20} />}
                      triggerClassName={styles.menuTrigger}
                      items={[
                        {
                          id: 'toggle-ai',
                          label: employee.aiEnabled ? 'Отключить AI' : 'Включить AI',
                          onSelect: () => {
                            void toggleAi(employee.id, employee.name, !employee.aiEnabled);
                          },
                        },
                        {
                          id: 'security',
                          label: 'Показать события сотрудника',
                          icon: <ShieldCheck size={16} />,
                          onSelect: () => {
                            showToast('События доступны в разделе «Безопасность»');
                          },
                        },
                      ]}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {items.length === 0 && !isFetching ? (
            <p className={styles.empty}>Сотрудники не найдены. Измените условия поиска.</p>
          ) : null}
        </div>

        <footer className={styles.footer}>
          <span className={styles.shown}>
            Показано {items.length} из {data?.found ?? 0} сотрудников
          </span>
          <nav className={styles.pagination} aria-label="Страницы">
            <button
              type="button"
              className={styles.pageButton}
              aria-label="Предыдущая страница"
              disabled={page <= 1}
              onClick={() => {
                setPage((value) => value - 1);
              }}
            >
              <ChevronLeft size={18} />
            </button>
            {Array.from({ length: Math.min(data?.pageCount ?? 1, 5) }, (_, index) => {
              const pageNumber = index + 1;
              return (
                <button
                  key={pageNumber}
                  type="button"
                  className={cx(styles.pageButton, page === pageNumber && styles.currentPage)}
                  aria-current={page === pageNumber ? 'page' : undefined}
                  onClick={() => {
                    setPage(pageNumber);
                  }}
                >
                  {pageNumber}
                </button>
              );
            })}
            <button
              type="button"
              className={styles.pageButton}
              aria-label="Следующая страница"
              disabled={page >= (data?.pageCount ?? 1)}
              onClick={() => {
                setPage((value) => value + 1);
              }}
            >
              <ChevronRight size={18} />
            </button>
          </nav>
        </footer>
      </AdminCard>

      <div className={styles.notes}>
        <div className={styles.note}>
          <span className={styles.noteIcon}>
            <Info size={24} />
          </span>
          <div>
            <p className={styles.noteTitle}>Что происходит при отключении AI?</p>
            <p className={styles.noteText}>
              Отключается только AI-помощник. Обычная рабочая почта продолжает работать в штатном
              режиме. Сотрудник по-прежнему может отправлять и получать письма.
            </p>
          </div>
        </div>
        <div className={styles.note}>
          <span className={styles.noteIcon}>
            <ShieldCheck size={24} />
          </span>
          <div>
            <p className={styles.noteTitle}>Конфиденциальность</p>
            <p className={styles.noteText}>
              Администратор не имеет доступа к содержанию личных писем сотрудников. Доступно только
              управление настройками и статусами.
            </p>
          </div>
        </div>
      </div>
    </AdminLayout>
  );
};
