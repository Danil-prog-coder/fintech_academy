/** Промис, который разрешается через `ms` миллисекунд (имитация сетевой задержки). */
export const delay = (ms: number): Promise<void> =>
  new Promise((resolve) => {
    setTimeout(resolve, ms);
  });

/** Время в формате ЧЧ:ММ. */
export const formatTime = (date: Date = new Date()): string =>
  date.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
