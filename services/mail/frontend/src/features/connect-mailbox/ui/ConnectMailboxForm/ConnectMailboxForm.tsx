import { Plug } from 'lucide-react';
import { useState } from 'react';

import {
  accountSelected,
  useConnectAccountMutation,
  type AccountCreate,
  type Security,
} from '@/entities/mailbox';
import { getErrorMessage } from '@/shared/api';
import { useAppDispatch } from '@/shared/lib/store';
import { showToast } from '@/shared/lib/toast';
import { Button, Notice, Select, TextField, Toggle } from '@/shared/ui';

import styles from './ConnectMailboxForm.module.css';
import { AppPasswordGuide } from '../AppPasswordGuide/AppPasswordGuide';

interface ConnectMailboxFormProps {
  onConnected: () => void;
}

const securityOptions = [
  { value: 'ssl', label: 'SSL/TLS' },
  { value: 'starttls', label: 'STARTTLS' },
  { value: 'none', label: 'Без шифрования' },
] as const;

interface ServerFields {
  host: string;
  port: string;
  security: Security;
}

const toServer = (server: ServerFields) => ({
  host: server.host.trim() || undefined,
  port: server.port.trim() ? Number(server.port) : undefined,
  security: server.host.trim() ? server.security : undefined,
});

interface ServerFieldsetProps {
  title: string;
  value: ServerFields;
  onChange: (value: ServerFields) => void;
}

const ServerFieldset = ({ title, value, onChange }: ServerFieldsetProps) => (
  <fieldset className={styles.fieldset}>
    <legend className={styles.legend}>{title}</legend>
    <div className={styles.serverRow}>
      <TextField
        label={`${title}: адрес сервера`}
        placeholder="mail.example.com"
        required
        value={value.host}
        onChange={(host) => {
          onChange({ ...value, host });
        }}
      />
      <TextField
        label={`${title}: порт`}
        placeholder="Порт"
        inputMode="numeric"
        pattern="[0-9]*"
        className={styles.port}
        value={value.port}
        onChange={(port) => {
          onChange({ ...value, port });
        }}
      />
    </div>
    <Select
      label={`${title}: шифрование`}
      fullWidth
      value={value.security}
      options={securityOptions}
      onChange={(security) => {
        onChange({ ...value, security });
      }}
    />
  </fieldset>
);

/** Подключение ящика по IMAP/SMTP; серверы известных доменов backend подставляет сам. */
export const ConnectMailboxForm = ({ onConnected }: ConnectMailboxFormProps) => {
  const dispatch = useAppDispatch();
  const [connect, { isLoading }] = useConnectAccountMutation();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [custom, setCustom] = useState(false);
  const [imap, setImap] = useState<ServerFields>({ host: '', port: '993', security: 'ssl' });
  const [smtp, setSmtp] = useState<ServerFields>({ host: '', port: '465', security: 'ssl' });
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setError(null);
    const body: AccountCreate = {
      email: email.trim(),
      password,
      display_name: displayName.trim() || undefined,
    };
    if (custom) {
      const imapServer = toServer(imap);
      const smtpServer = toServer(smtp);
      Object.assign(body, {
        imap_host: imapServer.host,
        imap_port: imapServer.port,
        imap_security: imapServer.security,
        smtp_host: smtpServer.host,
        smtp_port: smtpServer.port,
        smtp_security: smtpServer.security,
      });
    }
    try {
      const account = await connect(body).unwrap();
      dispatch(accountSelected(account.id));
      showToast(`Ящик ${account.email} подключён`, 'success');
      onConnected();
    } catch (cause) {
      setError(getErrorMessage(cause, 'Не удалось подключить ящик.'));
    }
  };

  return (
    <form
      className={styles.form}
      onSubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
    >
      <TextField
        label="Адрес почты"
        type="email"
        placeholder="name@example.com"
        autoComplete="email"
        required
        size="lg"
        value={email}
        onChange={setEmail}
      />
      <TextField
        label="Пароль приложения"
        type="password"
        placeholder="Пароль приложения"
        autoComplete="off"
        required
        size="lg"
        value={password}
        onChange={setPassword}
      />
      <p className={styles.hint}>
        Нужен именно пароль приложения (не основной пароль от почты): его создают в настройках
        безопасности почтового сервиса. Он хранится на сервере в зашифрованном виде.
      </p>
      <AppPasswordGuide email={email} />
      <TextField
        label="Имя отправителя"
        placeholder="Имя отправителя (необязательно)"
        value={displayName}
        onChange={setDisplayName}
      />
      <Toggle
        label="Свои серверы IMAP/SMTP (для незнакомого домена)"
        showLabel
        checked={custom}
        onChange={setCustom}
      />
      {custom ? (
        <>
          <ServerFieldset title="Входящая почта (IMAP)" value={imap} onChange={setImap} />
          <ServerFieldset title="Исходящая почта (SMTP)" value={smtp} onChange={setSmtp} />
        </>
      ) : null}
      {error ? <Notice tone="danger">{error}</Notice> : null}
      <Button
        type="submit"
        variant="primary"
        size="lg"
        fullWidth
        disabled={isLoading}
        icon={<Plug size={20} />}
      >
        {isLoading ? 'Проверяем подключение…' : 'Подключить ящик'}
      </Button>
    </form>
  );
};
