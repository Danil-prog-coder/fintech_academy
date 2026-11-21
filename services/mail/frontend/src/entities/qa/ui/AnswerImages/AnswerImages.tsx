import { useEffect, useState } from 'react';

import { env } from '@/shared/config';
import { getAccessToken } from '@/shared/lib/tokens';

import styles from './AnswerImages.module.css';
import { type AnswerImage } from '../../model/types';

/** Скриншот из документации. Картинка закрыта авторизацией, поэтому грузится через fetch, а не <img src>. */
const AuthImage = ({ image }: { image: AnswerImage }) => {
  const [src, setSrc] = useState<string | null>(null);

  useEffect(() => {
    let url: string | null = null;
    let cancelled = false;
    const token = getAccessToken();
    void fetch(`${env.apiUrl}/platform/images/${image.id}`, {
      headers: token ? { authorization: `Bearer ${token}` } : {},
    })
      .then((r) => (r.ok ? r.blob() : null))
      .then((blob) => {
        if (blob && !cancelled) {
          url = URL.createObjectURL(blob);
          setSrc(url);
        }
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
      if (url) {
        URL.revokeObjectURL(url);
      }
    };
  }, [image.id]);

  return src ? <img className={styles.image} src={src} alt="Иллюстрация из документации" /> : null;
};

export const AnswerImages = ({ images }: { images: AnswerImage[] }) =>
  images.length === 0 ? null : (
    <div className={styles.images}>
      {images.map((image) => (
        <AuthImage key={image.id} image={image} />
      ))}
    </div>
  );
