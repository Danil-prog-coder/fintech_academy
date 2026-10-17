export interface User {
  id: string;
  name: string;
  initials: string;
  email: string;
  roleLabel?: string;
}

/** Текущий сотрудник в почте (демонстрационные данные). */
export const currentUser: User = {
  id: 'u-kuznetsov',
  name: 'Иван Кузнецов',
  initials: 'ИК',
  email: 'i.kuznetsov@company.ru',
};

/** Администратор организации в кабинете (демонстрационные данные). */
export const adminUser: User = {
  id: 'u-admin',
  name: 'Алексей Петров',
  initials: 'АП',
  email: 'a.petrov@demo.ru',
  roleLabel: 'Администратор',
};
