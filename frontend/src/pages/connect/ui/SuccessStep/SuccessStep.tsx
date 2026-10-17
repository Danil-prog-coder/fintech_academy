import { ArrowRight, Check, CircleCheck, Folder, Lock, Mail } from 'lucide-react';
import { useNavigate } from 'react-router';

import { routePaths } from '@/shared/config';
import { cx } from '@/shared/lib/cx';
import { Badge, Button } from '@/shared/ui';

import styles from './SuccessStep.module.css';

const steps = [
  { id: 1, title: 'Выбор источников', description: 'Укажите, какие сервисы подключить' },
  { id: 2, title: 'Настройка доступа', description: 'Войдите через корпоративную учётную запись' },
  { id: 3, title: 'Готово к работе', description: 'Все выбранные источники подключены' },
];

const sources = [
  {
    id: 'mail',
    icon: <Mail size={34} strokeWidth={1.6} />,
    title: 'Корпоративная почта: подключена',
    description: 'Доступ к вашей рабочей почте настроен.',
    scope: 'Чтение писем и вложений',
  },
  {
    id: 'docs',
    icon: <Folder size={34} strokeWidth={1.6} />,
    title: 'Общие документы: доступ разрешён',
    description: 'Доступ к корпоративным документам настроен.',
    scope: 'Чтение документов',
  },
];

/** E-01: подключение выполнено. */
export const SuccessStep = () => {
  const navigate = useNavigate();

  return (
    <div className={styles.step}>
      <aside className={styles.aside}>
        <p className={styles.eyebrow}>Подключения</p>
        <h2 className={styles.asideTitle}>Интеграция с вашими рабочими сервисами</h2>
        <p className={styles.asideText}>
          Подключите корпоративную почту и документы, чтобы работать с ними в SOLUTIONS.
        </p>
        <ol className={styles.stepper}>
          {steps.map((item) => (
            <li key={item.id} className={cx(styles.stepperItem, item.id === 3 && styles.final)}>
              <span className={styles.stepperMarker}>
                {item.id === 3 ? <Check size={20} strokeWidth={3} /> : item.id}
              </span>
              <span>
                <span className={styles.stepperTitle}>{item.title}</span>
                <span className={styles.stepperText}>{item.description}</span>
              </span>
            </li>
          ))}
        </ol>
      </aside>
      <section className={styles.main}>
        <span className={styles.success} aria-hidden="true">
          <Check size={44} strokeWidth={3} />
        </span>
        <h1 className={styles.title}>Готово к работе</h1>
        <p className={styles.subtitle}>
          Помощник подключён к вашей корпоративной почте.
          <br />
          Вернитесь в привычный почтовый интерфейс.
        </p>
        <div className={styles.cards}>
          {sources.map((source) => (
            <article key={source.id} className={styles.card}>
              <span className={styles.cardIcon}>{source.icon}</span>
              <div className={styles.cardBody}>
                <p className={styles.cardTitle}>{source.title}</p>
                <p className={styles.cardText}>{source.description}</p>
                <p className={styles.scope}>
                  <CircleCheck size={18} />
                  {source.scope}
                </p>
              </div>
              <Badge tone="success" dot>
                Подключено
              </Badge>
            </article>
          ))}
          <article className={cx(styles.card, styles.policy)}>
            <span className={cx(styles.cardIcon, styles.neutralIcon)}>
              <Lock size={30} strokeWidth={1.6} />
            </span>
            <div className={styles.cardBody}>
              <p className={styles.cardTitle}>
                Доступ может быть ограничен корпоративной политикой
              </p>
              <p className={styles.cardText}>
                В зависимости от настроек вашей организации некоторые письма, вложения или документы
                могут быть недоступны в SOLUTIONS.
              </p>
            </div>
          </article>
        </div>
        <Button
          variant="primary"
          size="lg"
          className={styles.cta}
          iconAfter={<ArrowRight size={22} />}
          onClick={() => {
            void navigate(routePaths.mail);
          }}
        >
          Перейти к почте
        </Button>
      </section>
    </div>
  );
};
