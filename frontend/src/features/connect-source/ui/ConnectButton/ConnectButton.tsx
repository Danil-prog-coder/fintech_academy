import { Check, Plug } from 'lucide-react';

import { useAppDispatch, useAppSelector } from '@/shared/lib/store';
import { Button, Spinner } from '@/shared/ui';

import styles from './ConnectButton.module.css';
import { type ConnectionKind } from '../../model/connectionSlice';
import { connectSource } from '../../model/connectSource';

interface ConnectButtonProps {
  kind: ConnectionKind;
  primary?: boolean;
}

export const ConnectButton = ({ kind, primary = false }: ConnectButtonProps) => {
  const dispatch = useAppDispatch();
  const status = useAppSelector((state) => state.connection[kind]);

  if (status === 'connected') {
    return (
      <Button
        variant="soft"
        size="lg"
        icon={<Check size={20} />}
        disabled
        className={styles.button}
      >
        Подключено
      </Button>
    );
  }

  const connecting = status === 'connecting' || status === 'reauthorizing';

  return (
    <Button
      variant={primary ? 'primary' : 'secondary'}
      size="lg"
      className={styles.button}
      icon={connecting ? <Spinner size="sm" /> : <Plug size={20} />}
      disabled={connecting}
      onClick={() => {
        void dispatch(connectSource(kind));
      }}
    >
      {connecting ? 'Подключаем…' : 'Подключить'}
    </Button>
  );
};
