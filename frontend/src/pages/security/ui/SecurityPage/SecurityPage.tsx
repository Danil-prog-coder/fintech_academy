import { Info } from 'lucide-react';

import { Badge } from '@/shared/ui';
import { AdminLayout } from '@/widgets/admin-layout';

import styles from './SecurityPage.module.css';
import { EventJournal } from '../EventJournal/EventJournal';
import { PolicyList } from '../PolicyList/PolicyList';

/** A-04: корпоративные правила и журнал событий. Запрет блокирует действие, а не предупреждает. */
export const SecurityPage = () => (
  <AdminLayout
    title="Безопасность"
    subtitle="Управление политиками корпоративной безопасности и контроль событий."
    aside={
      <span className={styles.demo}>
        <Badge tone="accent" icon={<Info size={16} />}>
          Демонстрационные данные
        </Badge>
      </span>
    }
  >
    <PolicyList />
    <EventJournal />
  </AdminLayout>
);
