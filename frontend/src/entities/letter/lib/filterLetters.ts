import { type Letter, type LetterFilter } from '../model/types';

/** Фильтрация списка писем по вкладке и строке поиска. */
export const filterLetters = (letters: Letter[], filter: LetterFilter, search: string) => {
  const query = search.trim().toLowerCase();

  return letters.filter((letter) => {
    if (filter === 'unread' && !letter.unread) {
      return false;
    }
    if (filter === 'attachments' && !letter.hasAttachment) {
      return false;
    }
    if (!query) {
      return true;
    }
    return [letter.from.name, letter.from.email, letter.subject, letter.preview]
      .join(' ')
      .toLowerCase()
      .includes(query);
  });
};
