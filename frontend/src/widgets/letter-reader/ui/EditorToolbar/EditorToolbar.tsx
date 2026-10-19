import {
  Bold,
  ChevronDown,
  Ellipsis,
  Italic,
  Link,
  List,
  ListOrdered,
  Type,
  Underline,
} from 'lucide-react';

import { showToast } from '@/shared/lib/toast';
import { IconButton } from '@/shared/ui';

import styles from './EditorToolbar.module.css';

const notifyFormatting = () => {
  showToast('Форматирование выполняет редактор почтового клиента (демо)');
};

/** Стандартная панель форматирования редактора письма. */
export const EditorToolbar = () => (
  <div className={styles.toolbar} role="toolbar" aria-label="Форматирование">
    <button type="button" className={styles.select} onClick={notifyFormatting}>
      Inter <ChevronDown size={14} />
    </button>
    <span className={styles.divider} />
    <button type="button" className={styles.select} onClick={notifyFormatting}>
      16 <ChevronDown size={14} />
    </button>
    <span className={styles.divider} />
    <IconButton size="sm" label="Жирный" icon={<Bold size={18} />} onClick={notifyFormatting} />
    <IconButton size="sm" label="Курсив" icon={<Italic size={18} />} onClick={notifyFormatting} />
    <IconButton
      size="sm"
      label="Подчёркнутый"
      icon={<Underline size={18} />}
      onClick={notifyFormatting}
    />
    <IconButton
      size="sm"
      label="Цвет текста"
      icon={<Type size={18} />}
      onClick={notifyFormatting}
    />
    <span className={styles.divider} />
    <IconButton size="sm" label="Список" icon={<List size={18} />} onClick={notifyFormatting} />
    <IconButton
      size="sm"
      label="Нумерованный список"
      icon={<ListOrdered size={18} />}
      onClick={notifyFormatting}
    />
    <span className={styles.divider} />
    <IconButton size="sm" label="Ссылка" icon={<Link size={18} />} onClick={notifyFormatting} />
    <IconButton size="sm" label="Ещё" icon={<Ellipsis size={18} />} onClick={notifyFormatting} />
  </div>
);
