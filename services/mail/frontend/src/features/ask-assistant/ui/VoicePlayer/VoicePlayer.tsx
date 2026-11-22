import { useEffect, useRef } from 'react';

import styles from './VoicePlayer.module.css';

interface VoicePlayerProps {
  audio: Blob;
}

export const VoicePlayer = ({ audio }: VoicePlayerProps) => {
  const player = useRef<HTMLAudioElement>(null);
  useEffect(() => {
    const element = player.current;
    if (!element) {
      return;
    }
    const url = URL.createObjectURL(audio);
    element.src = url;
    return () => {
      URL.revokeObjectURL(url);
    };
  }, [audio]);

  return <audio ref={player} className={styles.player} controls aria-label="Голосовое сообщение" />;
};
