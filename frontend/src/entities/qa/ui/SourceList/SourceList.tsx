import { ExternalLink, FileCode, Paperclip } from 'lucide-react';
import { useState } from 'react';

import { getErrorMessage } from '@/shared/api';

import styles from './SourceList.module.css';
import { useLazyGetSourceQuery } from '../../api/qaApi';
import { type Source } from '../../model/types';

const SourceItem = ({ source }: { source: Source }) => {
  const [expanded, setExpanded] = useState(false);
  const [load, { data, isFetching, error }] = useLazyGetSourceQuery();
  const text = data?.snippet ?? source.snippet;
  const attachment = source.kind === 'attachment';

  const toggle = () => {
    // У вложений фрагмент приходит целиком: загружать с сервера нечего.
    if (!expanded && !data && source.id !== null) {
      void load(source.id, true);
    }
    setExpanded((value) => !value);
  };

  return (
    <li className={styles.item}>
      <div className={styles.head}>
        {attachment ? <Paperclip size={16} /> : <FileCode size={16} />}
        <span className={styles.path}>{source.path}</span>
        {attachment ? <span className={styles.commit}>вложение</span> : null}
        {source.commit_sha ? (
          <span className={styles.commit}>{source.commit_sha.slice(0, 7)}</span>
        ) : null}
        {source.url ? (
          <a
            className={styles.open}
            href={source.url}
            target="_blank"
            rel="noreferrer noopener"
            aria-label={`Открыть ${source.path} на GitHub`}
          >
            <ExternalLink size={16} />
          </a>
        ) : null}
      </div>
      <pre className={expanded ? styles.snippetFull : styles.snippet}>{text}</pre>
      <button type="button" className={styles.more} onClick={toggle}>
        {expanded ? 'Свернуть' : 'Показать полностью'}
      </button>
      {isFetching ? <span className={styles.note}>Загрузка…</span> : null}
      {error ? <span className={styles.note}>{getErrorMessage(error)}</span> : null}
    </li>
  );
};

const sourceKey = (source: Source, index: number) =>
  source.id === null ? `attachment-${String(index)}-${source.path}` : String(source.id);

export const SourceList = ({ sources }: { sources: Source[] }) =>
  sources.length === 0 ? null : (
    <section aria-label="Источники">
      <h4 className={styles.title}>Источники ({sources.length})</h4>
      <ul className={styles.list}>
        {sources.map((source, index) => (
          <SourceItem key={sourceKey(source, index)} source={source} />
        ))}
      </ul>
    </section>
  );
