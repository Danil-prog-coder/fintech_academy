import { ArrowRight, Check, Copy, FolderPlus, KeyRound } from 'lucide-react';
import { useState } from 'react';

import {
  roleLabel,
  useCreateProjectMutation,
  useEnterProject,
  useGetMeQuery,
  useGetMyProjectsQuery,
  useJoinProjectMutation,
  useSelectProjectMutation,
  type Me,
  type MyProject,
} from '@/entities/session';
import { AccountMenu } from '@/features/account-menu';
import { getErrorMessage } from '@/shared/api';
import { showToast } from '@/shared/lib/toast';
import {
  Badge,
  Button,
  Card,
  EmptyState,
  layout,
  Logo,
  Modal,
  Notice,
  Skeleton,
  TextField,
} from '@/shared/ui';

import styles from './ProjectsPage.module.css';

const ProjectList = ({ items }: { items: MyProject[] }) => {
  const enterProject = useEnterProject();
  const [select, { isLoading, error }] = useSelectProjectMutation();
  if (items.length === 0) {
    return (
      <EmptyState
        title="Пока нет проектов"
        text="Создайте свой проект или войдите в проект коллеги по его коду."
      />
    );
  }
  return (
    <>
      <ul className={layout.list}>
        {items.map((p) => (
          <li key={p.id} className={styles.project}>
            <span className={styles.projectName}>{p.name}</span>
            <Badge tone={p.role === 'owner' ? 'accent' : 'neutral'}>{roleLabel[p.role]}</Badge>
            {p.current ? (
              <Badge tone="success" icon={<Check size={12} />}>
                текущий
              </Badge>
            ) : null}
            <Button
              size="sm"
              variant="secondary"
              iconAfter={<ArrowRight size={16} />}
              disabled={isLoading}
              onClick={() => {
                void select(p.id)
                  .unwrap()
                  .then(enterProject)
                  .catch(() => undefined);
              }}
            >
              Открыть
            </Button>
          </li>
        ))}
      </ul>
      {error ? <Notice tone="danger">{getErrorMessage(error)}</Notice> : null}
    </>
  );
};

interface CodeModalProps {
  code: string;
  me: Me;
  onClose: () => void;
}

/** Код показывается один раз сразу после создания; потом его видит только владелец в «Настройках». */
const CodeModal = ({ code, me, onClose }: CodeModalProps) => {
  const enterProject = useEnterProject();
  const copy = () => {
    navigator.clipboard
      .writeText(code)
      .then(() => {
        showToast('Код скопирован', 'success');
      })
      .catch(() => {
        showToast('Не удалось скопировать — выделите код вручную', 'warning');
      });
  };
  return (
    <Modal
      open
      onClose={onClose}
      title={`Проект «${me.project?.name ?? ''}» создан`}
      description="Сохраните код проекта: с ним в проект входят ваши админы."
      footer={
        <div className={styles.actions}>
          <Button
            variant="primary"
            iconAfter={<ArrowRight size={18} />}
            onClick={() => {
              enterProject(me);
            }}
          >
            Перейти в проект
          </Button>
        </div>
      }
    >
      <div className={layout.stack}>
        <code className={styles.code}>{code}</code>
        <div className={styles.actions}>
          <Button size="sm" icon={<Copy size={16} />} onClick={copy}>
            Скопировать
          </Button>
        </div>
        <Notice tone="caution" compact>
          Передавайте код только тем, кого делаете админом: по нему входят в проект с правами
          админа. Если код попал не туда, выпустите новый в «Настройках».
        </Notice>
      </div>
    </Modal>
  );
};

const CreateProject = () => {
  const [name, setName] = useState('');
  const [create, { isLoading, error, data, reset }] = useCreateProjectMutation();
  return (
    <Card title="Создать проект">
      <p className={layout.muted}>
        Вы станете владельцем: загрузите документацию, назначите админов и поддержку.
      </p>
      <form
        className={layout.stack}
        onSubmit={(event) => {
          event.preventDefault();
          void create({ name: name.trim() })
            .unwrap()
            .then(() => {
              setName('');
            })
            .catch(() => undefined);
        }}
      >
        <TextField
          label="Название проекта"
          placeholder="Название проекта"
          maxLength={64}
          value={name}
          onChange={setName}
        />
        <Button
          type="submit"
          variant="primary"
          icon={<FolderPlus size={18} />}
          disabled={isLoading || !name.trim()}
        >
          Создать проект
        </Button>
      </form>
      {error ? <Notice tone="danger">{getErrorMessage(error)}</Notice> : null}
      {data ? <CodeModal code={data.project_code} me={data} onClose={reset} /> : null}
    </Card>
  );
};

const JoinAsAdmin = () => {
  const [code, setCode] = useState('');
  const enterProject = useEnterProject();
  const [join, { isLoading, error }] = useJoinProjectMutation();
  return (
    <Card title="Войти как админ">
      <p className={layout.muted}>Код проекта даёт владелец. С ним вы войдёте в проект админом.</p>
      <form
        className={layout.stack}
        onSubmit={(event) => {
          event.preventDefault();
          void join({ project_code: code.trim() })
            .unwrap()
            .then(enterProject)
            .catch(() => undefined);
        }}
      >
        <TextField
          label="Код проекта"
          placeholder="Код проекта"
          autoComplete="off"
          spellCheck={false}
          value={code}
          onChange={setCode}
        />
        <Button
          type="submit"
          variant="secondary"
          icon={<KeyRound size={18} />}
          disabled={isLoading || !code.trim()}
        >
          Войти как админ
        </Button>
      </form>
      {error ? <Notice tone="danger">{getErrorMessage(error)}</Notice> : null}
    </Card>
  );
};

/** После входа: свои проекты, создание проекта и вход админом по коду. */
export const ProjectsPage = () => {
  const { data: me } = useGetMeQuery(undefined);
  const { data, isLoading } = useGetMyProjectsQuery(undefined);

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <Logo caption="Панель проекта" />
        <span className={styles.spacer} />
        <AccountMenu canSwitchProject={Boolean(me?.project)} />
      </header>
      <main className={styles.main}>
        <h1 className={styles.title}>Проекты</h1>
        <Card title="Мои проекты">
          {isLoading || !data ? <Skeleton height={56} /> : <ProjectList items={data.projects} />}
        </Card>
        <div className={styles.choices}>
          <CreateProject />
          <JoinAsAdmin />
        </div>
        <p className={layout.muted}>
          Статус админа или поддержки назначили через почту или другую интеграцию? Откройте ссылку,
          которую вам прислали, — доступ добавится к этому аккаунту.
        </p>
      </main>
    </div>
  );
};
