import { ExternalLink, FileText } from 'lucide-react';

import styles from './SourceList.module.css';
import { type Source } from '../../model/types';

/** «Документ → раздел»: путь раздела у RAG уже начинается с названия документа — не повторяем его. */
const sourcePath = (source: Source) => {
  const title = source.document_title ?? '';
  const path = source.section_path ?? '';
  if (!path) {
    return title;
  }
  return !title || path.startsWith(title) ? path : `${title} → ${path}`;
};

/** Источники ответа: документ, раздел и дословная цитата; ссылка открывает документ на нужном месте. */
export const SourceList = ({ sources }: { sources: Source[] }) =>
  sources.length === 0 ? null : (
    <section aria-label="Источники">
      <h4 className={styles.title}>Источники ({sources.length})</h4>
      <ul className={styles.list}>
        {sources.map((source, index) => (
          <li key={`${String(index)}-${source.document_title ?? ''}`} className={styles.item}>
            <div className={styles.head}>
              <FileText size={16} />
              <span className={styles.commit}>
                {source.citation_label ?? source.label ?? `[${String(index + 1)}]`}
              </span>
              <span className={styles.path}>{sourcePath(source)}</span>
              {source.url ? (
                <a
                  className={styles.open}
                  href={source.url}
                  target="_blank"
                  rel="noreferrer noopener"
                  aria-label="Открыть документ"
                >
                  <ExternalLink size={16} />
                </a>
              ) : null}
            </div>
            {source.excerpt ? <p className={styles.snippetFull}>«{source.excerpt}»</p> : null}
          </li>
        ))}
      </ul>
    </section>
  );
