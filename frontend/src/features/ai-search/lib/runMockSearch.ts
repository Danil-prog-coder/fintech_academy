import { getDocumentById, type DocumentFile } from '@/entities/document';

import { type FoundLetter, type SearchRequest, type SearchResult } from '../model/types';

const contractLetter: FoundLetter = {
  id: 'f-contract',
  letterId: 'm-sergeeva',
  subject: 'Re: Согласование договора',
  from: 'Наталья Сергеева',
  initials: 'НС',
  dateLabel: '4 окт.',
  snippet: 'Иван, договор согласован с юридическим отделом. Можно переходить к подписанию.',
};

const legalArchiveLetter: FoundLetter = {
  id: 'f-legal',
  letterId: null,
  subject: 'Договор с подрядчиком: финальная редакция',
  from: 'Юридический отдел',
  initials: 'ЮО',
  dateLabel: '2 окт.',
  snippet: 'Направляем финальную редакцию договора. Замечаний со стороны юристов нет.',
};

const notFound = (title: string, text: string): SearchResult => ({
  kind: 'not_found',
  title,
  text,
});

const requireDocument = (id: string): DocumentFile => {
  const document = getDocumentById(id);
  if (!document) {
    throw new Error(`Документ ${id} отсутствует в демо-каталоге`);
  }
  return document;
};

/**
 * Демонстрационный AI-поиск по доступному сотруднику контексту.
 * Не выдумывает файлы и факты: если подтверждения нет — так и сообщает.
 */
export const runMockSearch = ({ query, context, attempt }: SearchRequest): SearchResult => {
  const text = [...context, query].join(' ').toLowerCase();

  if (text.includes('кто') && text.includes('согласова')) {
    if (text.includes('презентац')) {
      return {
        kind: 'answer',
        answer:
          'Презентацию согласовала Мария Петрова в письме от 10 октября. Согласована версия Презентация_v3.pptx.',
        sources: [
          {
            id: 's-1',
            kind: 'letter',
            title: 'Письмо руководителя',
            meta: '10 октября, Мария Петрова',
          },
          { id: 's-2', kind: 'document', title: 'Презентация_v3.pptx', meta: 'Общие документы' },
        ],
      };
    }
    return notFound(
      'Подтверждение не найдено',
      'В доступных материалах нет подтверждённого решения.',
    );
  }

  if (text.includes('смет')) {
    return {
      kind: 'document',
      document: requireDocument('doc-estimate'),
      reason:
        'Это наиболее релевантный файл, так как в названии и содержимом есть упоминания финансовой сметы текущего проекта.',
      basis: [
        {
          id: 'b-1',
          kind: 'document',
          title: 'Смета_проекта.xlsx',
          meta: 'Общие документы, 12 октября',
        },
        {
          id: 'b-2',
          kind: 'letter',
          title: 'Re: Бюджет проекта',
          meta: 'Ольга Лебедева, 9 октября',
        },
      ],
    };
  }

  if (text.includes('презентац')) {
    return {
      kind: 'multiple',
      items: [
        {
          document: requireDocument('doc-pres-final-v3'),
          recommended: true,
          explanation:
            'Эта версия считается финальной, так как её согласовала Мария Петрова в письме от 10 октября. В ней учтены все замечания.',
        },
        {
          document: requireDocument('doc-pres-final-v4'),
          recommended: false,
          explanation:
            'Более новая версия, но подтверждение согласования в письмах не найдено. Рекомендуем уточнить, актуальна ли она.',
        },
      ],
      note: 'Более поздняя дата файла не означает его согласование. Мы показываем версии и найденные подтверждения из переписки.',
    };
  }

  if (text.includes('договор')) {
    return attempt === 0
      ? { kind: 'letters', letters: [contractLetter], unavailableSource: 'Юридический архив' }
      : { kind: 'letters', letters: [contractLetter, legalArchiveLetter], unavailableSource: null };
  }

  if (/бюджет|сумм/.test(text)) {
    return notFound(
      'Подтверждение не найдено',
      'В доступных материалах нет подтверждённой суммы бюджета.',
    );
  }

  return notFound(
    'Ничего не найдено',
    'В доступных вам письмах и документах нет подходящих материалов.',
  );
};
