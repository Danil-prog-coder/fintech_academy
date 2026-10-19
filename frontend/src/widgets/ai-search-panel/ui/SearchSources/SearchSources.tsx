import { ExternalLink, FileText, Mail } from 'lucide-react';

import { type SearchSource } from '@/features/ai-search';
import { showToast } from '@/shared/lib/toast';

import styles from './SearchSources.module.css';

interface SearchSourcesProps {
  sources: SearchSource[];
}

/** Подтверждающие письма и документы; открываются с обычной проверкой доступа. */
export const SearchSources = ({ sources }: SearchSourcesProps) => (
  <ul className={styles.list}>
    {sources.map((source) => (
      <li key={source.id}>
        <button
          type="button"
          className={styles.source}
          onClick={() => {
            showToast(`Открываем «${source.title}» с обычной проверкой доступа`);
          }}
        >
          {source.kind === 'letter' ? <Mail size={18} /> : <FileText size={18} />}
          <span className={styles.text}>
            <span className={styles.title}>{source.title}</span>
            <span className={styles.meta}>{source.meta}</span>
          </span>
          <ExternalLink size={16} className={styles.open} />
        </button>
      </li>
    ))}
  </ul>
);
