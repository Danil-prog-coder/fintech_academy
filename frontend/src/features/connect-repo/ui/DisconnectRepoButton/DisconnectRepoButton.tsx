import { Unplug } from 'lucide-react';

import { useDisconnectRepoMutation } from '@/entities/repo';
import { getErrorMessage } from '@/shared/api';
import { showToast } from '@/shared/lib/toast';
import { Button } from '@/shared/ui';

export const DisconnectRepoButton = () => {
  const [disconnect, { isLoading }] = useDisconnectRepoMutation();

  const handleClick = async () => {
    if (!window.confirm('Отключить репозиторий? Индекс и вебхук будут удалены.')) {
      return;
    }
    try {
      await disconnect(undefined).unwrap();
      showToast('Репозиторий отключён', 'success');
    } catch (cause) {
      showToast(getErrorMessage(cause, 'Не удалось отключить репозиторий'), 'danger');
    }
  };

  return (
    <Button
      variant="danger"
      icon={<Unplug size={18} />}
      disabled={isLoading}
      onClick={() => void handleClick()}
    >
      Отключить
    </Button>
  );
};
