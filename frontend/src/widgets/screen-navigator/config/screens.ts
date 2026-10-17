import { routePaths } from '@/shared/config';

export type ScreenId =
  | 'S01'
  | 'S02'
  | 'S03'
  | 'S04'
  | 'S05'
  | 'S06'
  | 'S07'
  | 'S08'
  | 'S09'
  | 'S10'
  | 'S11'
  | 'S12'
  | 'S13'
  | 'S14'
  | 'S15'
  | 'S16'
  | 'S17'
  | 'S18'
  | 'S19'
  | 'S20'
  | 'S21'
  | 'S22'
  | 'S23'
  | 'S24'
  | 'S25'
  | 'S26';

export interface ScreenInfo {
  id: ScreenId;
  title: string;
  path: string;
}

export interface ScreenGroup {
  title: string;
  screens: ScreenInfo[];
}

/** Каталог 26 экранов из макетов SOLUTIONS (для быстрой проверки состояний). */
export const screenGroups: ScreenGroup[] = [
  {
    title: 'Письмо и ответ',
    screens: [
      { id: 'S01', title: 'Открытое письмо до запуска AI', path: routePaths.mail },
      { id: 'S02', title: 'AI подготавливает ответ', path: routePaths.mail },
      { id: 'S03', title: 'Готовый AI-черновик', path: routePaths.mail },
      { id: 'S04', title: 'Частично подготовленный ответ', path: routePaths.mail },
      { id: 'S05', title: 'Выбор версии вложения', path: routePaths.mail },
      { id: 'S06', title: 'Проверка фактов и источников', path: routePaths.mail },
      { id: 'S07', title: 'Уточнение готового ответа', path: routePaths.mail },
      { id: 'S08', title: 'Почта, AI-поиск закрыт', path: routePaths.mail },
      { id: 'S24', title: 'Противоречие в найденных фактах', path: routePaths.mail },
      { id: 'S25', title: 'Заблокированное вложение', path: routePaths.mail },
      { id: 'S26', title: 'Ошибка AI, черновик сохранён', path: routePaths.mail },
    ],
  },
  {
    title: 'AI-поиск',
    screens: [
      { id: 'S09', title: 'Открытая панель AI-поиска', path: routePaths.mail },
      { id: 'S10', title: 'AI-поиск выполняется', path: routePaths.mail },
      { id: 'S11', title: 'Найден нужный документ', path: routePaths.mail },
      { id: 'S12', title: 'Найдено несколько подходящих файлов', path: routePaths.mail },
      { id: 'S13', title: 'Ничего не найдено', path: routePaths.mail },
      { id: 'S14', title: 'Поиск выполнен не полностью', path: routePaths.mail },
    ],
  },
  {
    title: 'Подключение',
    screens: [
      { id: 'S15', title: 'Первый запуск', path: routePaths.connect },
      { id: 'S16', title: 'Подключение выполнено', path: routePaths.connect },
      { id: 'S17', title: 'Организация запретила подключение', path: routePaths.connect },
      { id: 'S18', title: 'Требуется повторная авторизация', path: routePaths.connect },
    ],
  },
  {
    title: 'Администрирование',
    screens: [
      { id: 'S19', title: 'Обзор организации', path: routePaths.admin },
      { id: 'S20', title: 'Сотрудники и доступы', path: routePaths.adminEmployees },
      { id: 'S21', title: 'Управление источниками', path: routePaths.adminSources },
      { id: 'S22', title: 'Корпоративная безопасность', path: routePaths.adminSecurity },
      { id: 'S23', title: 'Организация и роли', path: routePaths.adminOrganization },
    ],
  },
];
