import { Sparkles } from 'lucide-react';

import { useAppDispatch, useAppSelector } from '@/shared/lib/store';
import { Button, Spinner } from '@/shared/ui';

import styles from './PrepareReplyButton.module.css';
import { selectAiReply } from '../../model/aiReplySlice';
import { prepareReply } from '../../model/prepareReply';

interface PrepareReplyButtonProps {
  letterId: string;
  disabled?: boolean;
  label?: string;
}

export const PrepareReplyButton = ({
  letterId,
  disabled = false,
  label = 'Подготовить ответ',
}: PrepareReplyButtonProps) => {
  const dispatch = useAppDispatch();
  const { status } = useAppSelector((state) => selectAiReply(state, letterId));
  const preparing = status === 'preparing';

  return (
    <Button
      variant="primary"
      size="lg"
      className={styles.button}
      icon={preparing ? <Spinner size="sm" /> : <Sparkles size={20} />}
      disabled={disabled || preparing}
      onClick={() => {
        void dispatch(prepareReply({ letterId }));
      }}
    >
      {preparing ? 'Подготавливаем…' : label}
    </Button>
  );
};
