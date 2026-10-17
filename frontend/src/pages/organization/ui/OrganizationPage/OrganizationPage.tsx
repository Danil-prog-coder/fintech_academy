import {
  ExternalLink,
  EllipsisVertical,
  FileText,
  Lock,
  Mail,
  MessageSquare,
  Phone,
  ShieldCheck,
  UserPlus,
  Users,
  type LucideIcon,
} from 'lucide-react';

import {
  useGetAdminRolesQuery,
  useGetOrganizationQuery,
  useGetOrgSettingsQuery,
  useSetOrgSettingToggleMutation,
  type OrgSetting,
} from '@/entities/organization';
import { showToast } from '@/shared/lib/toast';
import { Avatar, Badge, Button, DropdownMenu, Logo, Skeleton, Toggle } from '@/shared/ui';
import { AdminCard, AdminLayout } from '@/widgets/admin-layout';

import styles from './OrganizationPage.module.css';

const settingIcons: Record<OrgSetting['id'], LucideIcon> = {
  notifications: Mail,
  securityPolicy: ShieldCheck,
  invites: Users,
  auditRetention: FileText,
};

const roleLabels = { admin: 'Администратор', security: 'Специалист ИБ' } as const;

/** A-05: организация, роли администраторов, базовые настройки и поддержка. */
export const OrganizationPage = () => {
  const { data: organization } = useGetOrganizationQuery(undefined);
  const { data: roles = [] } = useGetAdminRolesQuery(undefined);
  const { data: settings = [] } = useGetOrgSettingsQuery(undefined);
  const [setToggle] = useSetOrgSettingToggleMutation();

  return (
    <AdminLayout title="Организация" subtitle="Сведения об организации, роли и основные настройки">
      <AdminCard title="Сведения об организации">
        {organization ? (
          <div className={styles.orgGrid}>
            <div className={styles.org}>
              <span className={styles.orgLogo}>
                <Logo size="lg" withText={false} />
              </span>
              <div className={styles.orgInfo}>
                <p className={styles.orgName}>
                  {organization.name} <Badge tone="neutral">Демонстрационные данные</Badge>
                </p>
                <p className={styles.muted}>{organization.description}</p>
                <dl className={styles.details}>
                  <div className={styles.detailsColumn}>
                    <dt>ИНН</dt>
                    <dd>{organization.inn}</dd>
                    <dt>Отрасль</dt>
                    <dd>{organization.industry}</dd>
                    <dt>Сотрудников</dt>
                    <dd>{organization.employees}</dd>
                  </div>
                  <div className={styles.detailsColumn}>
                    <dt>Дата подключения</dt>
                    <dd>{organization.connectedAt}</dd>
                    <dt>Тариф</dt>
                    <dd>{organization.plan}</dd>
                    <dt>Статус</dt>
                    <dd>
                      <Badge tone="success" dot plain>
                        {organization.active ? 'Активна' : 'Приостановлена'}
                      </Badge>
                    </dd>
                  </div>
                </dl>
              </div>
            </div>
            <div className={styles.lockNotice}>
              <span className={styles.lockIcon}>
                <Lock size={26} />
              </span>
              <div>
                <p className={styles.lockTitle}>
                  Административная роль не даёт доступа к закрытой переписке
                </p>
                <p className={styles.muted}>
                  Администраторы и специалисты ИБ управляют настройками, сотрудниками и источниками,
                  но не могут читать чужую закрытую переписку и просматривать содержимое писем.
                </p>
              </div>
            </div>
          </div>
        ) : (
          <Skeleton height={160} />
        )}
      </AdminCard>

      <div className={styles.row}>
        <AdminCard
          title="Роли и пользователи"
          description="Управление ролями с административными полномочиями."
          actions={
            <Button
              variant="primary"
              icon={<UserPlus size={18} />}
              onClick={() => {
                showToast('Назначение роли выполняется из списка сотрудников (демо)');
              }}
            >
              Добавить пользователя
            </Button>
          }
        >
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Пользователь</th>
                  <th>Роль</th>
                  <th>Статус</th>
                  <th>Назначен</th>
                  <th>Действия</th>
                </tr>
              </thead>
              <tbody>
                {roles.map((role) => (
                  <tr key={role.id}>
                    <td>
                      <span className={styles.person}>
                        <Avatar initials={role.initials} tone="accent" size="sm" />
                        <span>
                          <span className={styles.personName}>{role.name}</span>
                          <span className={styles.muted}>{role.email}</span>
                        </span>
                      </span>
                    </td>
                    <td>
                      <Badge tone="accent">{roleLabels[role.role]}</Badge>
                    </td>
                    <td>
                      <Badge tone="success" dot plain>
                        {role.active ? 'Активен' : 'Отключён'}
                      </Badge>
                    </td>
                    <td className={styles.muted}>{role.assignedAt}</td>
                    <td>
                      <DropdownMenu
                        label={`Действия: ${role.name}`}
                        trigger={<EllipsisVertical size={20} />}
                        triggerClassName={styles.menuTrigger}
                        items={[
                          {
                            id: 'change',
                            label: 'Изменить роль',
                            onSelect: () => {
                              showToast(
                                'Изменение роли требует подтверждения второго администратора (демо)',
                              );
                            },
                          },
                          {
                            id: 'revoke',
                            label: 'Отозвать полномочия',
                            danger: true,
                            onSelect: () => {
                              showToast(
                                'Нельзя отозвать полномочия последнего администратора',
                                'warning',
                              );
                            },
                          },
                        ]}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </AdminCard>

        <AdminCard
          title="Контакт поддержки"
          description="По вопросам работы сервиса и настройке организации."
        >
          <ul className={styles.support}>
            <li>
              <a className={styles.supportItem} href="mailto:support@solutions.example">
                <Mail size={24} />
                <span>
                  <span className={styles.supportTitle}>support@solutions.example</span>
                  <span className={styles.muted}>Ответим в течение рабочего дня</span>
                </span>
              </a>
            </li>
            <li>
              <a className={styles.supportItem} href="tel:+78000000000">
                <Phone size={24} />
                <span>
                  <span className={styles.supportTitle}>8 800 000-00-00</span>
                  <span className={styles.muted}>Пн–Пт, 9:00 – 18:00 (МСК)</span>
                </span>
              </a>
            </li>
            <li>
              <button
                type="button"
                className={styles.supportItem}
                onClick={() => {
                  showToast('База знаний откроется в новой вкладке (демо)');
                }}
              >
                <FileText size={24} />
                <span>
                  <span className={styles.supportTitle}>База знаний</span>
                  <span className={styles.muted}>Инструкции и ответы на частые вопросы</span>
                </span>
                <ExternalLink size={20} className={styles.external} />
              </button>
            </li>
            <li>
              <button
                type="button"
                className={styles.supportItem}
                onClick={() => {
                  showToast('Форма запроса в поддержку откроется в новой вкладке (демо)');
                }}
              >
                <MessageSquare size={24} />
                <span>
                  <span className={styles.supportTitle}>Написать в поддержку</span>
                  <span className={styles.muted}>Открыть запрос</span>
                </span>
                <ExternalLink size={20} className={styles.external} />
              </button>
            </li>
          </ul>
        </AdminCard>
      </div>

      <AdminCard title="Основные настройки" description="Базовые параметры организации.">
        <ul className={styles.settings}>
          {settings.map((setting) => {
            const Icon = settingIcons[setting.id];
            return (
              <li key={setting.id} className={styles.setting}>
                <Icon size={22} />
                <span className={styles.settingTitle}>{setting.title}</span>
                <span className={styles.muted}>{setting.description}</span>
                <span className={styles.settingValue}>{setting.value}</span>
                <span className={styles.settingToggle}>
                  {setting.toggle === null ? null : (
                    <Toggle
                      label={setting.title}
                      checked={setting.toggle}
                      onChange={(enabled) => {
                        void setToggle({ id: setting.id, enabled });
                      }}
                    />
                  )}
                </span>
                <Button
                  size="sm"
                  variant="soft"
                  onClick={() => {
                    showToast(`Изменение параметра «${setting.title}» (демо)`);
                  }}
                >
                  Изменить
                </Button>
              </li>
            );
          })}
        </ul>
      </AdminCard>
    </AdminLayout>
  );
};
