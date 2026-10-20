import { ThumbsDown, ThumbsUp } from 'lucide-react';
import { useState } from 'react';

import { getErrorMessage } from '@/shared/api';
import { Button } from '@/shared/ui';

import styles from './FeedbackButtons.module.css';
import { useSendFeedbackMutation } from '../../api/qaApi';
import { type FeedbackTarget } from '../../model/types';

interface FeedbackButtonsProps {
  target: FeedbackTarget;
}

/** «Помогло / Не помогло»: оценка отправляется один раз. */
export const FeedbackButtons = ({ target }: FeedbackButtonsProps) => {
  const [send, { isLoading }] = useSendFeedbackMutation();
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const rate = async (helpful: boolean) => {
    setError(null);
    try {
      await send({ ...target, helpful }).unwrap();
      setSent(true);
    } catch (cause) {
      setError(getErrorMessage(cause, 'Не удалось отправить оценку.'));
    }
  };

  if (sent) {
    return <p className={styles.thanks}>Спасибо за оценку!</p>;
  }
  return (
    <div className={styles.row}>
      <span className={styles.label}>Ответ помог?</span>
      <Button
        size="sm"
        icon={<ThumbsUp size={14} />}
        disabled={isLoading}
        onClick={() => void rate(true)}
      >
        Помогло
      </Button>
      <Button
        size="sm"
        icon={<ThumbsDown size={14} />}
        disabled={isLoading}
        onClick={() => void rate(false)}
      >
        Не помогло
      </Button>
      {error ? <span className={styles.error}>{error}</span> : null}
    </div>
  );
};
