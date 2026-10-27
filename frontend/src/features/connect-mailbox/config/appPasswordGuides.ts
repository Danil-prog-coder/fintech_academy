export type MailProvider = 'gmail' | 'mailru' | 'yandex';

interface GuideStep {
  text: string;
  link?: { href: string; label: string };
}

interface AppPasswordGuide {
  provider: MailProvider;
  title: string;
  /** Домены ящиков сервиса; совпадают с пресетами серверов на backend. */
  domains: readonly string[];
  steps: readonly GuideStep[];
  note?: string;
}

/** Инструкции по созданию пароля приложения в популярных почтовых сервисах. */
export const appPasswordGuides: readonly AppPasswordGuide[] = [
  {
    provider: 'gmail',
    title: 'Gmail',
    domains: ['gmail.com', 'googlemail.com'],
    steps: [
      {
        text: 'Включите двухэтапную аутентификацию в аккаунте Google — без неё пароли приложений недоступны.',
        link: {
          href: 'https://myaccount.google.com/signinoptions/twosv',
          label: 'Двухэтапная аутентификация',
        },
      },
      {
        text: 'Откройте страницу паролей приложений.',
        link: { href: 'https://myaccount.google.com/apppasswords', label: 'Пароли приложений' },
      },
      { text: 'Введите название, например «Solutions», и нажмите «Создать».' },
      { text: 'Скопируйте 16-символьный пароль и вставьте его в поле выше без пробелов.' },
    ],
    note: 'Раздел недоступен в рабочих и учебных аккаунтах, а также при включённой «Дополнительной защите».',
  },
  {
    provider: 'mailru',
    title: 'Mail.ru',
    domains: ['mail.ru', 'inbox.ru', 'list.ru', 'bk.ru', 'internet.ru'],
    steps: [
      {
        text: 'Откройте «Все настройки» → «Безопасность» → «Пароли для внешних приложений».',
        link: {
          href: 'https://account.mail.ru/user/2-step-auth/passwords/',
          label: 'Пароли для внешних приложений',
        },
      },
      { text: 'Нажмите «Добавить» и введите название, например «Solutions».' },
      { text: 'Выберите полный доступ к Почте: нужны и чтение (IMAP), и отправка писем (SMTP).' },
      { text: 'Скопируйте пароль и вставьте его в поле выше — он показывается только один раз.' },
    ],
  },
  {
    provider: 'yandex',
    title: 'Яндекс',
    domains: ['yandex.ru', 'yandex.com', 'ya.ru', 'yandex.by', 'yandex.kz'],
    steps: [
      {
        text: 'Откройте Яндекс ID → «Безопасность» → «Пароли приложений».',
        link: { href: 'https://id.yandex.ru/security/app-passwords', label: 'Пароли приложений' },
      },
      { text: 'Выберите почтовое приложение, придумайте название и нажмите «Далее».' },
      { text: 'Скопируйте пароль и вставьте его в поле выше — он показывается только один раз.' },
      {
        text: 'В настройках Почты включите доступ «С сервера imap.yandex.ru по протоколу IMAP» и способ авторизации «Пароли приложений и OAuth-токены».',
        link: { href: 'https://mail.yandex.ru/#setup/client', label: 'Почтовые программы' },
      },
    ],
    note: 'Новый пароль может заработать не сразу — если вход не проходит, повторите попытку чуть позже.',
  },
];
