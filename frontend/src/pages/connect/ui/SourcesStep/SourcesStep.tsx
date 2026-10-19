import { ArrowRight, ShieldCheck } from 'lucide-react';
import { useNavigate } from 'react-router';

import { selectDocumentsConnection, selectMailConnection } from '@/features/connect-source';
import { routePaths } from '@/shared/config';
import { useAppSelector } from '@/shared/lib/store';
import { Button } from '@/shared/ui';

import styles from './SourcesStep.module.css';
import { SourceConnectCard } from '../SourceConnectCard/SourceConnectCard';

/** E-01: первый запуск — подключение корпоративных источников. */
export const SourcesStep = () => {
  const navigate = useNavigate();
  const mail = useAppSelector(selectMailConnection);
  const documents = useAppSelector(selectDocumentsConnection);

  return (
    <div className={styles.step}>
      <div className={styles.intro}>
        <h1 className={styles.title}>Подключите рабочую почту</h1>
        <p className={styles.subtitle}>
          Чтобы SOLUTIONS мог работать с вашими данными, подключите корпоративные источники.
          <br />
          Это займёт несколько минут.
        </p>
      </div>
      <SourceConnectCard kind="mail" status={mail} highlighted={mail !== 'connected'} />
      <SourceConnectCard
        kind="documents"
        status={documents}
        highlighted={mail === 'connected' && documents !== 'connected'}
      />
      <div className={styles.security}>
        <ShieldCheck size={36} strokeWidth={1.6} />
        <div>
          <p className={styles.securityTitle}>Безопасно и конфиденциально</p>
          <p className={styles.securityText}>
            SOLUTIONS получает доступ только к тем данным, которые разрешены в вашей организации.
            <br />
            Мы не сохраняем пароли и не отправляем письма от вашего имени.
          </p>
        </div>
      </div>
      {mail === 'connected' && documents !== 'connected' ? (
        <div className={styles.skip}>
          <Button
            variant="link"
            iconAfter={<ArrowRight size={16} />}
            onClick={() => {
              void navigate(routePaths.mail);
            }}
          >
            Продолжить без документов
          </Button>
        </div>
      ) : null}
    </div>
  );
};
