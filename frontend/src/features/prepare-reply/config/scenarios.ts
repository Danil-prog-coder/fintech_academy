/**
 * Демонстрационные сценарии AI-ответа. В реальном продукте результат определяется
 * анализом письма и доступных источников; здесь сценарий выбирается заранее.
 */
export type ReplyScenario =
  'complete' | 'partial' | 'facts' | 'conflict' | 'blocked' | 'error' | 'generic';

/** Сценарии, которые можно выбрать для основного демонстрационного письма. */
export type DemoScenario = 'complete' | 'partial' | 'facts' | 'conflict' | 'error';

interface ScenarioContent {
  text: (firstName: string) => string;
  attachmentId: string | null;
  /** Значимые фрагменты, требующие внимания (подсвечиваются в редакторе). */
  highlights: string[];
}

export const BUDGET_AMOUNT = '2 500 000 ₽';

export const scenarioContent: Record<Exclude<ReplyScenario, 'error'>, ScenarioContent> = {
  complete: {
    text: (name) =>
      `${name}, добрый день!\n\nНаправляю финальную презентацию проекта.\nСумма бюджета требует подтверждения, уточню её отдельно.`,
    attachmentId: 'doc-pres-final',
    highlights: [],
  },
  partial: {
    text: (name) =>
      `${name}, добрый день!\n\nНаправляю финальную презентацию проекта.\nСумму бюджета уточню и сообщу отдельно после внутреннего согласования.`,
    attachmentId: 'doc-pres-final',
    highlights: [],
  },
  facts: {
    text: (name) =>
      `${name}, добрый день!\n\nНаправляю финальную презентацию проекта.\nСумма ${BUDGET_AMOUNT} требует подтверждения.`,
    attachmentId: 'doc-pres-final',
    highlights: [],
  },
  conflict: {
    text: (name) =>
      `${name}, добрый день!\n\nНаправляю финальную презентацию проекта.\nСумма бюджета проекта составляет ${BUDGET_AMOUNT}.\nПожалуйста, подтвердите, что эта сумма актуальна.\n\nС уважением,\nИван Кузнецов`,
    attachmentId: 'doc-pres-final',
    highlights: [BUDGET_AMOUNT],
  },
  blocked: {
    text: () =>
      'Добрый день!\nПроверю, какие финансовые материалы разрешены к передаче, и вернусь с ответом.',
    attachmentId: 'doc-finance-report',
    highlights: [],
  },
  generic: {
    text: (name) =>
      `${name}, добрый день!\n\nСпасибо за письмо. В доступных материалах не нашлось подтверждённой информации по вашему вопросу — уточню детали и вернусь с ответом.`,
    attachmentId: null,
    highlights: [],
  },
};

/** Какой сценарий применяется к письму. */
export const resolveScenario = (letterId: string, demoScenario: DemoScenario): ReplyScenario => {
  if (letterId === 'm-client') {
    return 'blocked';
  }
  if (letterId === 'm-petrova') {
    return demoScenario;
  }
  return 'generic';
};

export const PREPARATION_STEPS = [
  { title: 'Анализ запроса', description: 'Определяем ключевые вопросы', durationMs: 900 },
  {
    title: 'Поиск доступных материалов',
    description: 'Ищем актуальные файлы и данные',
    durationMs: 1100,
  },
  {
    title: 'Проверка фактов',
    description: 'Сверяем информацию и готовим ответ',
    durationMs: 900,
  },
] as const;
