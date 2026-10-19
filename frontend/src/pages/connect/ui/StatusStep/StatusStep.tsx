import { CircleCheck, FileText, Lock, Mail, ShieldCheck, UserPlus, X } from 'lucide-react';
import { useNavigate } from 'react-router';

import {
  connectionStatusChanged,
  connectSource,
  selectMailConnection,
} from '@/features/connect-source';
import { routePaths } from '@/shared/config';
import { useAppDispatch, useAppSelector } from '@/shared/lib/store';
import { showToast } from '@/shared/lib/toast';
import { Button, Spinner } from '@/shared/ui';

import styles from './StatusStep.module.css';

interface StatusStepProps {
  variant: 'forbidden' | 'reauth';
}

const features = [
  {
    id: 'mail',
    icon: <Mail size={26} />,
    title: 'Письма и переписка',
    text: 'Чтение писем, анализ переписки и вложений.',
  },
  {
    id: 'docs',
    icon: <FileText size={26} />,
    title: 'Документы',
    text: 'Доступ к внутренним документам вашей компании.',
  },
  {
    id: 'security',
    icon: <ShieldCheck size={26} />,
    title: 'Безопасно и конфиденциально',
    text: 'Доступ только к тем данным, которые разрешены в вашей организации.',
  },
];

/** E-01: подключение запрещено политикой (без обхода) или требуется повторная авторизация. */
export const StatusStep = ({ variant }: StatusStepProps) => {
  const dispatch = useAppDispatch();
  const navigate = useNavigate();
  const mail = useAppSelector(selectMailConnection);
  const connecting = mail === 'reauthorizing';

  if (variant === 'forbidden') {
    return (
      <div className={styles.step}>
        <aside className={styles.aside}>
          <h1 className={styles.asideTitle}>Подключите рабочую почту</h1>
          <p className={styles.asideText}>
            Чтобы SOLUTIONS мог работать с вашими данными, подключите корпоративные источники.
          </p>
          <ul className={styles.features}>
            {features.map((feature) => (
              <li key={feature.id} className={styles.feature}>
                <span className={styles.featureIcon}>{feature.icon}</span>
                <span>
                  <span className={styles.featureTitle}>{feature.title}</span>
                  <span className={styles.featureText}>{feature.text}</span>
                </span>
              </li>
            ))}
          </ul>
        </aside>
        <section className={styles.card}>
          <span className={styles.illustrationDanger} aria-hidden="true">
            <Lock size={56} strokeWidth={1.8} />
            <span className={styles.illustrationBadge}>
              <X size={22} strokeWidth={3} />
            </span>
          </span>
          <h2 className={styles.title}>Подключение недоступно</h2>
          <p className={styles.lead}>Доступ ограничен политикой организации.</p>
          <p className={styles.text}>
            В вашей компании действует ограничение на подключение корпоративной почты к внешним
            приложениям. Для получения доступа обратитесь к администратору организации.
          </p>
          <div className={styles.actions}>
            <Button
              variant="primary"
              size="lg"
              className={styles.primaryAction}
              icon={<UserPlus size={22} />}
              onClick={() => {
                showToast('Запрос на доступ подготовлен для администратора организации (демо)');
              }}
            >
              Связаться с администратором
            </Button>
            <Button
              size="lg"
              className={styles.secondaryAction}
              onClick={() => {
                dispatch(connectionStatusChanged({ kind: 'mail', status: 'not_connected' }));
              }}
            >
              Назад
            </Button>
          </div>
        </section>
      </div>
    );
  }

  return (
    <div className={styles.step}>
      <aside className={styles.aside}>
        <h1 className={styles.asideTitle}>Обновите подключение</h1>
        <p className={styles.asideText}>
          Срок подключения истёк. Подтвердите доступ к корпоративной почте, чтобы помощник продолжил
          работу в рамках политики компании.
        </p>
      </aside>
      <section className={styles.card}>
        <span className={styles.illustrationWarning} aria-hidden="true">
          <Mail size={56} strokeWidth={1.8} />
          <span className={styles.illustrationBadgeWarning}>!</span>
        </span>
        <h2 className={styles.title}>Корпоративная почта</h2>
        <span className={styles.statusPill}>Требует авторизации</span>
        <p className={styles.text}>
          Срок подключения истёк. Подтвердите доступ к корпоративной почте, чтобы помощник продолжил
          работу в рамках политики компании.
        </p>
        <p className={styles.safe}>
          <CircleCheck size={26} />
          Письма и сохранённые черновики не удалены.
        </p>
        <div className={styles.actions}>
          <Button
            variant="primary"
            size="lg"
            className={styles.primaryAction}
            icon={connecting ? <Spinner size="sm" /> : <UserPlus size={22} />}
            disabled={connecting}
            onClick={() => {
              void dispatch(connectSource('mail'));
            }}
          >
            {connecting ? 'Подключаем…' : 'Авторизоваться'}
          </Button>
          <Button
            size="lg"
            className={styles.secondaryAction}
            disabled={connecting}
            onClick={() => {
              void navigate(routePaths.mail);
            }}
          >
            Позже
          </Button>
        </div>
      </section>
    </div>
  );
};
