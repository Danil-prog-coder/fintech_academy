import { baseApi } from '@/shared/api';
import { delay } from '@/shared/lib/time';

import {
  type ActivityPoint,
  type AdminRoleAssignment,
  type Organization,
  type OrgSetting,
  type OverviewStats,
  type SecurityPolicy,
} from '../model/types';

const organization: Organization = {
  name: 'Демо-компания',
  description: 'Использует SOLUTIONS для безопасной работы с корпоративной почтой и документами.',
  inn: '7701234567',
  industry: 'Информационные технологии',
  employees: 126,
  connectedAt: '1 апр. 2026 г.',
  plan: 'Бизнес',
  active: true,
};

const adminRoles: AdminRoleAssignment[] = [
  {
    id: 'r-1',
    name: 'Алексей Петров',
    initials: 'АП',
    email: 'a.petrov@demo.ru',
    role: 'admin',
    active: true,
    assignedAt: '1 апр. 2026',
  },
  {
    id: 'r-2',
    name: 'Ирина Смирнова',
    initials: 'ИС',
    email: 'i.smirnova@demo.ru',
    role: 'security',
    active: true,
    assignedAt: '12 апр. 2026',
  },
];

let orgSettings: OrgSetting[] = [
  {
    id: 'notifications',
    title: 'Уведомления',
    description: 'Важные события и отчёты по организации',
    value: 'Включены',
    toggle: true,
  },
  {
    id: 'securityPolicy',
    title: 'Политика безопасности',
    description: 'Базовые правила работы с источниками',
    value: 'Стандартная',
    toggle: null,
  },
  {
    id: 'invites',
    title: 'Приглашение сотрудников',
    description: 'Кто может приглашать новых сотрудников',
    value: 'Только администраторы',
    toggle: null,
  },
  {
    id: 'auditRetention',
    title: 'Журнал действий',
    description: 'Срок хранения событий в организации',
    value: '12 месяцев',
    toggle: null,
  },
];

let securityPolicies: SecurityPolicy[] = [
  {
    id: 'transfer',
    title: 'Передача данных AI',
    description: 'Использование данных и предложенных вложений вне компании.',
    value: 'Только внутри компании',
    options: ['Только внутри компании', 'Доверенные домены', 'Без ограничений'],
    enabled: true,
  },
  {
    id: 'retention',
    title: 'Хранение данных AI',
    description: 'Срок хранения результатов работы AI по политике компании.',
    value: '6 месяцев',
    options: ['1 месяц', '3 месяца', '6 месяцев', '12 месяцев'],
    enabled: true,
  },
  {
    id: 'features',
    title: 'Права на функции AI',
    description: 'Кто может использовать AI-помощника и AI-поиск.',
    value: 'Все сотрудники',
    options: ['Все сотрудники', 'Выбранные отделы', 'Только администраторы'],
    enabled: true,
  },
  {
    id: 'attachments',
    title: 'Вложения',
    description: 'Разрешить скачивание вложений из писем.',
    value: 'Только для доверенных доменов',
    options: ['Только для доверенных доменов', 'Для всех доменов', 'Запрещено'],
    enabled: true,
  },
  {
    id: 'links',
    title: 'Внешние ссылки',
    description: 'Разрешить переход по ссылкам во внешние сервисы.',
    value: 'С проверкой безопасности',
    options: ['С проверкой безопасности', 'Без проверки', 'Запрещено'],
    enabled: true,
  },
];

/** Детерминированный «живой» ряд активности за 30 дней. */
const createActivity = (): ActivityPoint[] =>
  Array.from({ length: 30 }, (_, index) => {
    const day = index + 1;
    return {
      label: `${String(day)} окт`,
      drafts: Math.round(42 + 12 * Math.sin(day / 2.2) + day * 0.45),
      searches: Math.round(20 + 6 * Math.sin(day / 1.7 + 1) + day * 0.35),
    };
  });

export const organizationApi = baseApi.injectEndpoints({
  endpoints: (build) => ({
    getOrganization: build.query<Organization, undefined>({
      queryFn: async () => {
        await delay(200);
        return { data: organization };
      },
      providesTags: ['Organization'],
    }),
    getAdminRoles: build.query<AdminRoleAssignment[], undefined>({
      queryFn: async () => {
        await delay(200);
        return { data: adminRoles };
      },
      providesTags: ['Organization'],
    }),
    getOrgSettings: build.query<OrgSetting[], undefined>({
      queryFn: async () => {
        await delay(200);
        return { data: orgSettings };
      },
      providesTags: ['Organization'],
    }),
    setOrgSettingToggle: build.mutation<undefined, { id: OrgSetting['id']; enabled: boolean }>({
      queryFn: async ({ id, enabled }) => {
        await delay(200);
        orgSettings = orgSettings.map((setting) =>
          setting.id === id
            ? { ...setting, toggle: enabled, value: enabled ? 'Включены' : 'Выключены' }
            : setting,
        );
        return { data: undefined };
      },
      invalidatesTags: ['Organization'],
    }),
    getOverviewStats: build.query<OverviewStats, undefined>({
      queryFn: async () => {
        await delay(250);
        return {
          data: {
            employees: 126,
            active: 84,
            drafts: 1204,
            searches: 358,
            trends: { employees: '+12%', active: '+8%', drafts: '+18%', searches: '+25%' },
            activity: createActivity(),
          },
        };
      },
      providesTags: ['Organization'],
    }),
    getSecurityPolicies: build.query<SecurityPolicy[], undefined>({
      queryFn: async () => {
        await delay(200);
        return { data: securityPolicies };
      },
      providesTags: ['Organization'],
    }),
    saveSecurityPolicies: build.mutation<undefined, SecurityPolicy[]>({
      queryFn: async (policies) => {
        await delay(500);
        securityPolicies = policies;
        return { data: undefined };
      },
      invalidatesTags: ['Organization'],
    }),
  }),
});

export const {
  useGetOrganizationQuery,
  useGetAdminRolesQuery,
  useGetOrgSettingsQuery,
  useSetOrgSettingToggleMutation,
  useGetOverviewStatsQuery,
  useGetSecurityPoliciesQuery,
  useSaveSecurityPoliciesMutation,
} = organizationApi;
