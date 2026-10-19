const sameDay = (a: Date, b: Date) =>
  a.getFullYear() === b.getFullYear() &&
  a.getMonth() === b.getMonth() &&
  a.getDate() === b.getDate();

const time = (date: Date) =>
  date.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });

/** «10:24», «Вчера 18:03» или «15.10.2026 14:12». */
export const formatEventTimeShort = (iso: string, now: Date = new Date()) => {
  const date = new Date(iso);
  if (sameDay(date, now)) {
    return time(date);
  }
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (sameDay(date, yesterday)) {
    return `Вчера ${time(date)}`;
  }
  return formatEventTimeFull(iso);
};

export const formatEventTimeFull = (iso: string) => {
  const date = new Date(iso);
  return `${date.toLocaleDateString('ru-RU')} ${time(date)}`;
};
