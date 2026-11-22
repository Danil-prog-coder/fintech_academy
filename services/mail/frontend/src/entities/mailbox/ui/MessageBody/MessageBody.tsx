import { useCallback, useState } from 'react';

import styles from './MessageBody.module.css';

interface MessageBodyProps {
  html: string | null;
  text: string | null;
}

/** Сервер уже очистил HTML; поверх этого — изолированный iframe без скриптов и без сети. */
const CSP = "default-src 'none'; img-src data: blob:; style-src 'unsafe-inline'; font-src data:";

const buildDocument = (html: string) =>
  `<!doctype html><html><head><meta charset="utf-8">` +
  `<meta http-equiv="Content-Security-Policy" content="${CSP}">` +
  `<base target="_blank">` +
  `<style>body{margin:0;padding:0;font:15px/1.5 system-ui,sans-serif;color:#141414;` +
  `overflow-wrap:anywhere}img{max-width:100%;height:auto}</style></head>` +
  `<body>${html}</body></html>`;

export const MessageBody = ({ html, text }: MessageBodyProps) => {
  const [height, setHeight] = useState(240);

  const fit = useCallback((frame: HTMLIFrameElement) => {
    const doc = frame.contentDocument;
    if (doc) {
      setHeight(Math.max(doc.documentElement.scrollHeight, 120));
    }
  }, []);

  if (html) {
    return (
      <iframe
        className={styles.frame}
        title="Содержимое письма"
        // allow-same-origin без allow-scripts: скрипты не выполняются, родитель лишь измеряет высоту.
        sandbox="allow-same-origin allow-popups"
        srcDoc={buildDocument(html)}
        style={{ height }}
        onLoad={(event) => {
          fit(event.currentTarget);
        }}
      />
    );
  }

  return <pre className={styles.text}>{text?.trim() ? text : '(пустое письмо)'}</pre>;
};
