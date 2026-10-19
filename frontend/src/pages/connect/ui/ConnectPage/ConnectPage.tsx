import { selectDocumentsConnection, selectMailConnection } from '@/features/connect-source';
import { useAppSelector } from '@/shared/lib/store';

import styles from './ConnectPage.module.css';
import { ConnectHeader } from '../ConnectHeader/ConnectHeader';
import { SourcesStep } from '../SourcesStep/SourcesStep';
import { StatusStep } from '../StatusStep/StatusStep';
import { SuccessStep } from '../SuccessStep/SuccessStep';

/** Подключение источников: первый запуск, успех, запрет организации, повторная авторизация. */
export const ConnectPage = () => {
  const mail = useAppSelector(selectMailConnection);
  const documents = useAppSelector(selectDocumentsConnection);

  const content =
    mail === 'forbidden' ? (
      <StatusStep variant="forbidden" />
    ) : mail === 'auth_required' || mail === 'reauthorizing' ? (
      <StatusStep variant="reauth" />
    ) : mail === 'connected' && documents === 'connected' ? (
      <SuccessStep />
    ) : (
      <SourcesStep />
    );

  return (
    <div className={styles.page}>
      <ConnectHeader />
      <main className={styles.main}>{content}</main>
    </div>
  );
};
