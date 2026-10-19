import { type Employee, type EmployeeStatus } from '../model/types';

const firstNames = [
  ['Ольга', 'Лебедева'],
  ['Сергей', 'Миронов'],
  ['Екатерина', 'Тихонова'],
  ['Дмитрий', 'Иванов'],
  ['Наталья', 'Сергеева'],
  ['Алексей', 'Климов'],
  ['Павел', 'Орлов'],
  ['Юлия', 'Морозова'],
  ['Андрей', 'Волков'],
  ['Ирина', 'Зайцева'],
  ['Максим', 'Соловьёв'],
  ['Татьяна', 'Белова'],
  ['Никита', 'Фролов'],
  ['Елена', 'Козлова'],
] as const;

const departments = ['Проектный офис', 'Финансы', 'Закупки', 'Юридический отдел', 'Маркетинг'];

const transliteration: Record<string, string> = {
  а: 'a',
  б: 'b',
  в: 'v',
  г: 'g',
  д: 'd',
  е: 'e',
  ё: 'e',
  ж: 'zh',
  з: 'z',
  и: 'i',
  й: 'y',
  к: 'k',
  л: 'l',
  м: 'm',
  н: 'n',
  о: 'o',
  п: 'p',
  р: 'r',
  с: 's',
  т: 't',
  у: 'u',
  ф: 'f',
  х: 'h',
  ц: 'ts',
  ч: 'ch',
  ш: 'sh',
  щ: 'sch',
  ъ: '',
  ы: 'y',
  ь: '',
  э: 'e',
  ю: 'yu',
  я: 'ya',
};

const toLatin = (value: string) =>
  value.toLowerCase().replace(/[а-яё]/g, (char) => transliteration[char] ?? char);

const pinned: Employee[] = [
  {
    id: 'e-1',
    name: 'Мария Петрова',
    initials: 'МП',
    email: 'm.petrova@company.ru',
    department: 'Проектный офис',
    role: 'employee',
    status: 'active',
    aiEnabled: true,
  },
  {
    id: 'e-2',
    name: 'Алексей Иванов',
    initials: 'АИ',
    email: 'a.ivanov@company.ru',
    department: 'Финансы',
    role: 'employee',
    status: 'disabled',
    aiEnabled: false,
  },
  {
    id: 'e-3',
    name: 'Анна Смирнова',
    initials: 'АС',
    email: 'a.smirnova@company.ru',
    department: 'Маркетинг',
    role: 'employee',
    status: 'pending',
    aiEnabled: true,
  },
];

/** 126 демонстрационных сотрудников: 84 активных, 9 в ожидании, 33 с отключённым AI. */
const generate = (): Employee[] => {
  const result = [...pinned];
  const counts: Record<EmployeeStatus, number> = { active: 83, pending: 8, disabled: 32 };
  const statuses: EmployeeStatus[] = [
    ...Array<EmployeeStatus>(counts.active).fill('active'),
    ...Array<EmployeeStatus>(counts.pending).fill('pending'),
    ...Array<EmployeeStatus>(counts.disabled).fill('disabled'),
  ];

  statuses.forEach((status, index) => {
    const pair = firstNames[index % firstNames.length] ?? firstNames[0];
    const [first, last] = pair;
    const suffix = Math.floor(index / firstNames.length);
    const email = `${toLatin(first).charAt(0)}.${toLatin(last)}${suffix ? String(suffix) : ''}@company.ru`;
    result.push({
      id: `e-${String(index + 4)}`,
      name: `${first} ${last}`,
      initials: `${first.charAt(0)}${last.charAt(0)}`,
      email,
      department: departments[index % departments.length] ?? 'Проектный офис',
      role: 'employee',
      status,
      aiEnabled: status !== 'disabled',
    });
  });

  return result;
};

export const createMockEmployees = generate;
