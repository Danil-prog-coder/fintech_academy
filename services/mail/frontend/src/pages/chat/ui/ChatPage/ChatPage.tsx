import { useGetProjectsQuery } from '@/entities/project';
import { useGetMeQuery } from '@/entities/session';
import { ChatPanel } from '@/features/ask-assistant';
import { AppHeader } from '@/widgets/app-header';

import styles from './ChatPage.module.css';

/** Чат с ассистентом по подключённому репозиторию. */
export const ChatPage = () => {
  const { data: me } = useGetMeQuery(undefined);
  const { data: projects } = useGetProjectsQuery(undefined);
  const projectId = projects?.current_project_id;
  const historyKey = me && projectId ? `mail.chat.${me.id}.${projectId}` : undefined;

  return (
    <div className={styles.page}>
      <AppHeader />
      <main className={styles.main}>
        <h1 className={styles.title}>Чат с ассистентом</h1>
        <div className={styles.chat}>
          <ChatPanel key={historyKey} historyKey={historyKey} projectId={projectId} />
        </div>
      </main>
    </div>
  );
};
