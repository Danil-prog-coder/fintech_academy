import {
  Ban,
  CircleQuestionMark,
  Database,
  ExternalLink,
  Lock,
  Mail,
  Paperclip,
  Users,
  type LucideIcon,
} from 'lucide-react';
import { useState } from 'react';

import { useLogAuditEventMutation } from '@/entities/audit-event';
import {
  useGetSecurityPoliciesQuery,
  useSaveSecurityPoliciesMutation,
  type PolicyId,
  type SecurityPolicy,
} from '@/entities/organization';
import { showToast } from '@/shared/lib/toast';
import { Button, Select, Skeleton, Spinner, Toggle } from '@/shared/ui';
import { AdminCard } from '@/widgets/admin-layout';

import styles from './PolicyList.module.css';

const icons: Record<PolicyId, LucideIcon> = {
  transfer: Mail,
  retention: Database,
  features: Users,
  attachments: Paperclip,
  links: ExternalLink,
};

/** Корпоративные правила: ограничения передачи, хранение, права на функции. */
export const PolicyList = () => {
  const { data, isLoading } = useGetSecurityPoliciesQuery(undefined);
  const [savePolicies, { isLoading: saving }] = useSaveSecurityPoliciesMutation();
  const [logEvent] = useLogAuditEventMutation();
  const [edited, setEdited] = useState<SecurityPolicy[] | null>(null);
  const policies = edited ?? data ?? [];

  const update = (id: PolicyId, patch: Partial<SecurityPolicy>) => {
    setEdited(policies.map((policy) => (policy.id === id ? { ...policy, ...patch } : policy)));
  };

  const save = async () => {
    if (!edited) {
      return;
    }
    await savePolicies(edited);
    await logEvent({
      type: 'policy',
      title: 'Изменение корпоративных правил AI',
      employee: 'Алексей П.',
      source: 'Системные настройки',
      status: 'success',
    });
    setEdited(null);
    showToast('Изменения сохранены и применены для всех сотрудников', 'success');
  };

  return (
    <AdminCard
      title="Корпоративные правила"
      description="Настройте политики передачи, хранения данных и права на функции. Изменения применяются для всех сотрудников."
      actions={
        <Button
          variant={edited ? 'primary' : 'soft'}
          disabled={!edited || saving}
          icon={saving ? <Spinner size="sm" /> : undefined}
          onClick={() => {
            void save();
          }}
        >
          Сохранить изменения
        </Button>
      }
    >
      {isLoading ? (
        <Skeleton height={300} />
      ) : (
        <ul className={styles.list}>
          {policies.map((policy) => {
            const Icon = icons[policy.id];
            return (
              <li key={policy.id} className={styles.row}>
                <Icon size={24} className={styles.icon} />
                <div className={styles.text}>
                  <p className={styles.title}>{policy.title}</p>
                  <p className={styles.description}>{policy.description}</p>
                </div>
                <Select
                  label={policy.title}
                  value={policy.value}
                  options={policy.options.map((option) => ({ value: option, label: option }))}
                  disabled={!policy.enabled}
                  onChange={(value) => {
                    update(policy.id, { value });
                  }}
                  size="sm"
                  fullWidth
                />
                <span className={styles.help} title={policy.description}>
                  <CircleQuestionMark size={20} />
                </span>
                <span className={styles.toggle}>
                  <Toggle
                    label={policy.enabled ? 'Включено' : 'Выключено'}
                    showLabel
                    checked={policy.enabled}
                    onChange={(enabled) => {
                      update(policy.id, { enabled });
                    }}
                  />
                </span>
              </li>
            );
          })}
          <li className={styles.row}>
            <Users size={24} className={styles.icon} />
            <div className={styles.text}>
              <p className={styles.title}>Доступ к закрытой переписке</p>
              <p className={styles.description}>
                Администраторы не имеют доступа к содержимому личной переписки сотрудников.
              </p>
            </div>
            <span className={styles.denied}>
              <Ban size={18} />
              Доступ запрещен
            </span>
            <span
              className={styles.help}
              title="Ни одна административная роль не открывает доступ к чужой закрытой переписке."
            >
              <CircleQuestionMark size={20} />
            </span>
            <span className={styles.locked}>
              <Lock size={20} />
              Недоступно для административных ролей
            </span>
          </li>
        </ul>
      )}
    </AdminCard>
  );
};
