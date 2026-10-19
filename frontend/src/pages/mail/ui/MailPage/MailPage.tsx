import { selectDrafts } from '@/entities/draft';
import { selectStarredIds } from '@/entities/letter';
import { selectSearchOpen } from '@/features/ai-search';
import { cx } from '@/shared/lib/cx';
import { useAppSelector } from '@/shared/lib/store';
import { AiSearchPanel } from '@/widgets/ai-search-panel';
import { LetterList } from '@/widgets/letter-list';
import { LetterReader } from '@/widgets/letter-reader';
import { MailHeader } from '@/widgets/mail-header';
import { MailSidebar } from '@/widgets/mail-sidebar';

import styles from './MailPage.module.css';

/** Привычный интерфейс почты с встроенным AI-ответом и правой панелью AI-поиска. */
export const MailPage = () => {
  const searchOpen = useAppSelector(selectSearchOpen);
  const drafts = useAppSelector(selectDrafts);
  const starredIds = useAppSelector(selectStarredIds);
  const draftsCount = Object.values(drafts).filter((draft) => draft.text.trim()).length;

  return (
    <div className={cx(styles.page, searchOpen && styles.withSearch)}>
      <div className={styles.sidebar}>
        <MailSidebar draftsCount={draftsCount} starredCount={starredIds.length} />
      </div>
      <div className={styles.header}>
        <MailHeader />
      </div>
      <div className={styles.list}>
        <LetterList />
      </div>
      <main className={styles.reader}>
        <LetterReader />
      </main>
      {searchOpen ? (
        <div className={styles.search}>
          <AiSearchPanel />
        </div>
      ) : null}
    </div>
  );
};
