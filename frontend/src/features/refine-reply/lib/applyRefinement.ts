export interface RefinementResult {
  text: string;
  changed: boolean;
  title: string;
  description: string;
}

const GREETING = /^[^\n]*добрый день!?\s*$/i;
const AMOUNT = /\d[\d\s]*\d\s?₽/;

/** Индекс первого содержательного абзаца (после приветствия). */
const findFirstContentParagraph = (paragraphs: string[]) =>
  paragraphs.findIndex((paragraph) => paragraph.trim() && !GREETING.test(paragraph.trim()));

/** Сокращает абзац: склеивает строки и убирает уточняющие хвосты предложений. */
const shortenParagraph = (paragraph: string) =>
  paragraph
    .split('\n')
    .map((line) =>
      line
        .replace(/ проекта\./, '.')
        .replace(/, уточню её отдельно\./, '.')
        .replace(/ и сообщу отдельно после внутреннего согласования\./, '.'),
    )
    .join(' ');

/**
 * Точечное изменение текста. Затрагивается только связанный фрагмент,
 * остальные (в том числе ручные) правки остаются как есть.
 */
export const applyRefinement = (text: string, query: string): RefinementResult => {
  const request = query.toLowerCase();
  const paragraphs = text.split('\n\n');
  const target = findFirstContentParagraph(paragraphs);
  const targetParagraph = paragraphs[target];

  if (/короч|сократ|кратк/.test(request)) {
    if (targetParagraph === undefined) {
      return { text, changed: false, title: 'Нечего сокращать', description: 'Черновик пуст.' };
    }
    const shortened = shortenParagraph(targetParagraph);
    paragraphs[target] = shortened;
    return {
      text: paragraphs.join('\n\n'),
      changed: shortened !== targetParagraph,
      title: 'Первый абзац сделан короче',
      description: 'Смысл сохранён. Остальные части без изменений.',
    };
  }

  if (/официальн|вежлив|формальн/.test(request)) {
    const greetingIndex = paragraphs.findIndex((paragraph) => GREETING.test(paragraph.trim()));
    if (greetingIndex === -1) {
      return {
        text,
        changed: false,
        title: 'Тон уже нейтральный',
        description: 'Приветствие не найдено — текст оставлен без изменений.',
      };
    }
    paragraphs.splice(greetingIndex + 1, 0, 'Благодарю за обращение.');
    return {
      text: paragraphs.join('\n\n'),
      changed: true,
      title: 'Тон сделан более официальным',
      description: 'Добавлена вежливая формулировка. Остальной текст не изменён.',
    };
  }

  if (request.includes('срок')) {
    if (targetParagraph === undefined) {
      return { text, changed: false, title: 'Черновик пуст', description: 'Нечего уточнять.' };
    }
    paragraphs[target] =
      `${targetParagraph}\nСрок подготовки материалов уточню и сообщу дополнительно.`;
    return {
      text: paragraphs.join('\n\n'),
      changed: true,
      title: 'Добавлена оговорка о сроке',
      description: 'Подтверждённый срок в источниках не найден, поэтому дата не указана.',
    };
  }

  if (/бюджет|сумм/.test(request)) {
    const lines = text.split('\n');
    const amountIndex = lines.findIndex((line) => AMOUNT.test(line));
    if (amountIndex !== -1) {
      // Неподтверждённая сумма заменяется оговоркой; просьба подтвердить её больше не нужна.
      const next = lines[amountIndex + 1] ?? '';
      lines.splice(
        amountIndex,
        next.startsWith('Пожалуйста, подтвердите') ? 2 : 1,
        'Сумму бюджета уточню после сверки источников и сообщу отдельно.',
      );
      return {
        text: lines.join('\n'),
        changed: true,
        title: 'Сумма заменена оговоркой',
        description:
          'В источниках нет одного подтверждённого значения — AI не выбирает сумму автоматически.',
      };
    }
    return {
      text,
      changed: false,
      title: 'Сумма не подтверждена',
      description:
        'В доступных источниках нет согласованной суммы, поэтому AI не подставляет её в ответ.',
    };
  }

  return {
    text,
    changed: false,
    title: 'Не удалось понять запрос',
    description: 'Попробуйте, например: «короче», «официальнее», «уточни срок».',
  };
};
