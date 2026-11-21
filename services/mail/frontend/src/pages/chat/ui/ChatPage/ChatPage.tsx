import { ChatPanel } from '@/features/ask-assistant';
import { AppHeader } from '@/widgets/app-header';

import styles from './ChatPage.module.css';

/** Чат с ассистентом по подключённому репозиторию. */
export const ChatPage = () => (
  <div className={styles.page}>
    <AppHeader />
    <main className={styles.main}>
      <h1 className={styles.title}>Чат с ассистентом</h1>
      <div className={styles.chat}>
        <ChatPanel />
      </div>
    </main>
  </div>
);
