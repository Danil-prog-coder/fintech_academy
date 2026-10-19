import {
  Archive,
  ArrowLeft,
  ChevronLeft,
  ChevronRight,
  Clock,
  EllipsisVertical,
  Folder,
  Mail,
  OctagonAlert,
  Trash,
} from 'lucide-react';

import { letterSelected, useGetLettersQuery } from '@/entities/letter';
import { useAppDispatch } from '@/shared/lib/store';
import { showToast } from '@/shared/lib/toast';
import { IconButton } from '@/shared/ui';

import styles from './LetterToolbar.module.css';

interface LetterToolbarProps {
  letterId: string;
}

const demoAction = (label: string) => () => {
  showToast(`${label} — действие выполняет почтовый клиент (демо)`);
};

export const LetterToolbar = ({ letterId }: LetterToolbarProps) => {
  const dispatch = useAppDispatch();
  const { data: letters = [] } = useGetLettersQuery('inbox');
  const index = letters.findIndex((letter) => letter.id === letterId);
  const previous = index > 0 ? letters[index - 1] : undefined;
  const next = index !== -1 ? letters[index + 1] : undefined;

  return (
    <div className={styles.toolbar}>
      <IconButton
        label="Назад к списку"
        icon={<ArrowLeft size={22} />}
        onClick={() => {
          dispatch(letterSelected(null));
        }}
      />
      <IconButton label="В архив" icon={<Archive size={20} />} onClick={demoAction('Архив')} />
      <IconButton label="Удалить" icon={<Trash size={20} />} onClick={demoAction('Удаление')} />
      <IconButton
        label="Спам"
        icon={<OctagonAlert size={20} />}
        onClick={demoAction('Пометка «Спам»')}
      />
      <IconButton
        label="Отметить непрочитанным"
        icon={<Mail size={20} />}
        onClick={demoAction('Отметка')}
      />
      <IconButton label="Отложить" icon={<Clock size={20} />} onClick={demoAction('Отложить')} />
      <IconButton
        label="Переместить"
        icon={<Folder size={20} />}
        onClick={demoAction('Перемещение')}
      />
      <IconButton label="Ещё" icon={<EllipsisVertical size={20} />} onClick={demoAction('Меню')} />
      <div className={styles.pager}>
        <IconButton
          label="Предыдущее письмо"
          icon={<ChevronLeft size={20} />}
          disabled={!previous}
          onClick={() => {
            if (previous) {
              dispatch(letterSelected(previous.id));
            }
          }}
        />
        <IconButton
          label="Следующее письмо"
          icon={<ChevronRight size={20} />}
          disabled={!next}
          onClick={() => {
            if (next) {
              dispatch(letterSelected(next.id));
            }
          }}
        />
      </div>
    </div>
  );
};
