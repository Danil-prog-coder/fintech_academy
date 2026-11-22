import { type Address } from '../model/types';

export const addressLabel = (address: Address | null): string =>
  address ? (address.name?.trim() ?? '') || address.email : 'Неизвестный отправитель';

export const addressFull = (address: Address): string =>
  address.name?.trim() ? `${address.name} <${address.email}>` : address.email;

export const initialsOf = (address: Address | null): string => {
  const source = address ? (address.name?.trim() ?? '') || address.email : '?';
  const words = source.split(/[\s@._-]+/).filter(Boolean);
  const letters = words.slice(0, 2).map((word) => word.charAt(0));
  return (letters.join('') || '?').toUpperCase();
};

const sameDay = (a: Date, b: Date) => a.toDateString() === b.toDateString();

/** Время для сегодняшних писем, дата для остальных. */
export const formatListDate = (iso: string | null): string => {
  if (!iso) {
    return '';
  }
  const date = new Date(iso);
  if (sameDay(date, new Date())) {
    return date.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
  }
  const sameYear = date.getFullYear() === new Date().getFullYear();
  return date.toLocaleDateString('ru-RU', {
    day: 'numeric',
    month: 'short',
    ...(sameYear ? {} : { year: 'numeric' }),
  });
};

export const formatFullDate = (iso: string | null): string =>
  iso
    ? new Date(iso).toLocaleString('ru-RU', {
        day: 'numeric',
        month: 'long',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      })
    : '';

export const formatSize = (bytes: number): string => {
  if (bytes < 1024) {
    return `${String(bytes)} Б`;
  }
  if (bytes < 1024 * 1024) {
    return `${String(Math.round(bytes / 1024))} КБ`;
  }
  return `${(bytes / 1024 / 1024).toFixed(1)} МБ`;
};

const FOLDER_LABELS: Record<string, string> = {
  inbox: 'Входящие',
  sent: 'Отправленные',
  drafts: 'Черновики',
  trash: 'Корзина',
  junk: 'Спам',
  archive: 'Архив',
};

export const folderLabel = (folder: { name: string; role: string | null }): string =>
  (folder.role ? FOLDER_LABELS[folder.role] : undefined) ?? folder.name;
