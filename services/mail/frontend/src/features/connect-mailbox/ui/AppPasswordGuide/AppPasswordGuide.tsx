import { ChevronDown, ExternalLink, KeyRound } from 'lucide-react';
import { useId, useState } from 'react';

import { cx } from '@/shared/lib/cx';

import styles from './AppPasswordGuide.module.css';
import { appPasswordGuides, type MailProvider } from '../../config/appPasswordGuides';
import { detectMailProvider } from '../../lib/detectMailProvider';

interface AppPasswordGuideProps {
  /** Введённый адрес: по его домену сразу открывается нужная инструкция. */
  email: string;
}

/** Раскрывающаяся инструкция, как получить пароль приложения в Gmail, Mail.ru и Яндексе. */
export const AppPasswordGuide = ({ email }: AppPasswordGuideProps) => {
  const panelId = useId();
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<MailProvider | null>(null);
  const detected = detectMailProvider(email);
  const active = selected ?? detected ?? 'gmail';
  const guide = appPasswordGuides.find((item) => item.provider === active);

  return (
    <div className={styles.guide}>
      <button
        type="button"
        className={styles.trigger}
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => {
          setOpen(!open);
        }}
      >
        <KeyRound size={16} className={styles.triggerIcon} />
        <span className={styles.triggerLabel}>Как получить пароль приложения</span>
        <ChevronDown size={18} className={cx(styles.chevron, open && styles.chevronOpen)} />
      </button>
      {open && guide ? (
        <div id={panelId} className={styles.panel}>
          <div className={styles.providers} role="group" aria-label="Почтовый сервис">
            {appPasswordGuides.map((item) => (
              <button
                key={item.provider}
                type="button"
                className={cx(styles.provider, item.provider === active && styles.providerActive)}
                aria-pressed={item.provider === active}
                onClick={() => {
                  setSelected(item.provider);
                }}
              >
                {item.title}
              </button>
            ))}
          </div>
          <ol className={styles.steps}>
            {guide.steps.map((step) => (
              <li key={step.text} className={styles.step}>
                {step.text}
                {step.link ? (
                  <a
                    className={styles.link}
                    href={step.link.href}
                    target="_blank"
                    rel="noreferrer noopener"
                  >
                    {step.link.label}
                    <ExternalLink size={12} className={styles.linkIcon} />
                  </a>
                ) : null}
              </li>
            ))}
          </ol>
          {guide.note ? <p className={styles.note}>{guide.note}</p> : null}
        </div>
      ) : null}
    </div>
  );
};
