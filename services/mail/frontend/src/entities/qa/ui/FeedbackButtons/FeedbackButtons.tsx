import { ThumbsDown, ThumbsUp } from 'lucide-react';
import { useState } from 'react';

import { getErrorMessage } from '@/shared/api';
import { Button } from '@/shared/ui';

import styles from './FeedbackButtons.module.css';
import { useSendFeedbackMutation } from '../../api/qaApi';

/** «Помогло / Не помогло»: «не помогло» отправляет вопрос администраторам проекта. */
export const FeedbackButtons = ({ requestId }: { requestId: string }) => {
  const [send, { isLoading }] = useSendFeedbackMutation();
  const [sent, setSent] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const rate = async (value: 1 | -1) => {
    setError(null);
    try {
      const res = await send({ request_id: requestId, value }).unwrap();
      setSent(
        res.question_id ? 'Спасибо! Вопрос передан администраторам проекта.' : 'Спасибо за оценку!',
      );
    } catch (cause) {
      setError(getErrorMessage(cause, 'Не удалось отправить оценку.'));
    }
  };

  if (sent) {
    return <p className={styles.thanks}>{sent}</p>;
  }
  return (
    <div className={styles.row}>
      <span className={styles.label}>Ответ помог?</span>
      <Button
        size="sm"
        icon={<ThumbsUp size={14} />}
        disabled={isLoading}
        onClick={() => void rate(1)}
      >
        Помогло
      </Button>
      <Button
        size="sm"
        icon={<ThumbsDown size={14} />}
        disabled={isLoading}
        onClick={() => void rate(-1)}
      >
        Не помогло
      </Button>
      {error ? <span className={styles.error}>{error}</span> : null}
    </div>
  );
};
