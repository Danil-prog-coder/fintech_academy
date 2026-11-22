import { Check, KeyRound, LogIn, Plus, Trash2, UserPlus } from 'lucide-react';
import { useState } from 'react';

import {
  roleLabel,
  useCreateProjectMutation,
  useDeleteMemberMutation,
  useGetMembersQuery,
  useGetProjectsQuery,
  useJoinProjectMutation,
  usePanelLinkMutation,
  usePutMemberMutation,
  useSelectProjectMutation,
  type CreatedProject,
  type JoinedProject,
  type Role,
} from '@/entities/project';
import { getErrorMessage } from '@/shared/api';
import {
  Badge,
  Button,
  EmptyState,
  IconButton,
  Notice,
  Select,
  Skeleton,
  TextField,
} from '@/shared/ui';
import { AppHeader } from '@/widgets/app-header';

import styles from './ProjectsPage.module.css';

type AssignableRole = Exclude<Role, 'owner'>;
const roleOptions: { value: AssignableRole; label: string }[] = [
  { value: 'user', label: 'Пользователь' },
  { value: 'admin', label: 'Админ (сайт администратора)' },
  { value: 'support', label: 'Поддержка (сайт администратора)' },
];

const OneTimeSecrets = ({ created }: { created: CreatedProject }) => (
  <Notice tone="success" title={`Проект «${created.project.name}» создан`}>
    <p>
      Код проекта — сохраните его сейчас, второй раз он не покажется:{' '}
      <code className={styles.code}>{created.project_code}</code>
    </p>
    <p>
      С этим кодом в проект входят админы — передавайте его только им. Документацию загружают на
      сайте администратора: откройте ссылку (действует 72 часа), войдите или зарегистрируйтесь там —
      проект добавится к вашему аккаунту:{' '}
      <a href={created.owner_panel_setup_url} target="_blank" rel="noreferrer noopener">
        {created.owner_panel_setup_url}
      </a>
    </p>
  </Notice>
);

const JoinProject = () => {
  const [code, setCode] = useState('');
  const [join, { isLoading, error }] = useJoinProjectMutation();
  const [joined, setJoined] = useState<JoinedProject | null>(null);
  return (
    <section className={styles.card} aria-label="Войти в проект по коду">
      <h2 className={styles.subtitle}>Войти в проект как админ</h2>
      <p className={styles.hint}>
        Код проекта даёт владелец — например, если проект создан на сайте администратора.
      </p>
      <form
        className={styles.row}
        onSubmit={(event) => {
          event.preventDefault();
          void join({ project_code: code.trim() })
            .unwrap()
            .then((res) => {
              setJoined(res);
              setCode('');
            })
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
          maxLength={64}
        />
        <Button
          type="submit"
          variant="secondary"
          icon={<LogIn size={16} />}
          disabled={isLoading || !code.trim()}
        >
          Войти
        </Button>
      </form>
      {error ? <Notice tone="danger">{getErrorMessage(error)}</Notice> : null}
      {joined ? (
        <Notice tone="success" title={`Вы в проекте «${joined.project.name}»`}>
          Ваш статус — {roleLabel[joined.project.role]}. Проект стал текущим: «Спросить у ИИ» и
          «Ответить с ИИ» ищут в его документации.
          {joined.panel_setup_url ? (
            <>
              {' '}
              Для сайта администратора откройте ссылку:{' '}
              <a href={joined.panel_setup_url} target="_blank" rel="noreferrer noopener">
                {joined.panel_setup_url}
              </a>
            </>
          ) : null}
        </Notice>
      ) : null}
    </section>
  );
};

const CreateProject = () => {
  const [name, setName] = useState('');
  const [login, setLogin] = useState('');
  const [create, { isLoading, error }] = useCreateProjectMutation();
  const [created, setCreated] = useState<CreatedProject | null>(null);
  return (
    <section className={styles.card} aria-label="Новый проект">
      <h2 className={styles.subtitle}>Новый проект</h2>
      <form
        className={styles.row}
        onSubmit={(event) => {
          event.preventDefault();
          void create({ name: name.trim(), login: login.trim() })
            .unwrap()
            .then((res) => {
              setCreated(res);
              setName('');
            })
            .catch(() => undefined);
        }}
      >
        <TextField
          label="Название"
          placeholder="Название проекта"
          value={name}
          onChange={setName}
          maxLength={64}
        />
        <TextField
          label="Логин"
          placeholder="Ваш логин на сайте администратора"
          value={login}
          onChange={setLogin}
          maxLength={64}
        />
        <Button
          type="submit"
          variant="primary"
          icon={<Plus size={16} />}
          disabled={isLoading || !name.trim() || login.trim().length < 3}
        >
          Создать
        </Button>
      </form>
      {error ? <Notice tone="danger">{getErrorMessage(error)}</Notice> : null}
      {created ? <OneTimeSecrets created={created} /> : null}
    </section>
  );
};

const Members = ({ projectId, myRole }: { projectId: string; myRole: Role }) => {
  const { data, error, isLoading } = useGetMembersQuery(projectId);
  const [put, putState] = usePutMemberMutation();
  const [remove] = useDeleteMemberMutation();
  const [link] = usePanelLinkMutation();
  const [email, setEmail] = useState('');
  const [role, setRole] = useState<AssignableRole>('user');
  const [login, setLogin] = useState('');
  const [note, setNote] = useState<string | null>(null);
  const manager = myRole === 'owner' || myRole === 'admin';
  const needsLogin = role !== 'user';

  const act = (p: Promise<unknown>) => {
    setNote(null);
    p.catch((cause: unknown) => {
      setNote(getErrorMessage(cause));
    });
  };

  return (
    <section className={styles.card} aria-label="Участники">
      <h2 className={styles.subtitle}>Участники проекта</h2>
      {isLoading ? <Skeleton height={80} /> : null}
      {error ? <Notice tone="danger">{getErrorMessage(error)}</Notice> : null}
      {data ? (
        <ul className={styles.list}>
          {data.members.map((m) => (
            <li key={m.external_id} className={styles.member}>
              <span className={styles.name}>{m.email ?? m.display_name ?? m.external_id}</span>
              <Badge tone={m.role === 'user' ? 'neutral' : 'accent'}>{roleLabel[m.role]}</Badge>
              {m.panel_login ? (
                <span className={styles.muted}>
                  сайт: {m.panel_login}
                  {m.panel_password_set ? '' : ' (пароль не задан)'}
                </span>
              ) : null}
              {myRole === 'owner' && m.email && m.panel_login ? (
                <IconButton
                  label="Ссылка для смены пароля"
                  size="sm"
                  icon={<KeyRound size={16} />}
                  onClick={() => {
                    act(
                      link({ projectId, email: m.email ?? '' })
                        .unwrap()
                        .then((r) => {
                          setNote(`Ссылка для пароля: ${r.panel_setup_url}`);
                        }),
                    );
                  }}
                />
              ) : null}
              {manager && m.role !== 'owner' && m.email ? (
                <IconButton
                  label="Удалить из проекта"
                  size="sm"
                  icon={<Trash2 size={16} />}
                  onClick={() => {
                    act(remove({ projectId, email: m.email ?? '' }).unwrap());
                  }}
                />
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
      {manager ? (
        <form
          className={styles.row}
          onSubmit={(event) => {
            event.preventDefault();
            act(
              put({
                projectId,
                body: { email: email.trim(), role, login: needsLogin ? login.trim() : undefined },
              })
                .unwrap()
                .then((r) => {
                  setEmail('');
                  setLogin('');
                  setNote(
                    r.panel_setup_url
                      ? `Добавлен. Ссылка, чтобы задать пароль на сайте: ${r.panel_setup_url}`
                      : 'Добавлен.',
                  );
                }),
            );
          }}
        >
          <TextField
            label="Email"
            placeholder="Email пользователя почты"
            value={email}
            onChange={setEmail}
          />
          <Select label="Статус" value={role} options={roleOptions} onChange={setRole} />
          {needsLogin ? (
            <TextField
              label="Логин"
              placeholder="Логин на сайте"
              value={login}
              onChange={setLogin}
            />
          ) : null}
          <Button
            type="submit"
            icon={<UserPlus size={16} />}
            disabled={
              putState.isLoading || !email.trim() || (needsLogin && login.trim().length < 3)
            }
          >
            Назначить
          </Button>
        </form>
      ) : null}
      {note ? <Notice tone="info">{note}</Notice> : null}
    </section>
  );
};

/** Проекты на платформе: создание, выбор текущего, статусы участников. */
export const ProjectsPage = () => {
  const { data, error, isLoading } = useGetProjectsQuery(undefined);
  const [select] = useSelectProjectMutation();
  const current = data?.projects.find((p) => p.id === data.current_project_id);

  return (
    <div className={styles.page}>
      <AppHeader />
      <main className={styles.main}>
        <h1 className={styles.title}>Проекты</h1>
        {isLoading ? <Skeleton height={120} /> : null}
        {error ? <Notice tone="danger">{getErrorMessage(error)}</Notice> : null}
        {data ? (
          <section className={styles.card} aria-label="Мои проекты">
            <h2 className={styles.subtitle}>Мои проекты</h2>
            {data.projects.length === 0 ? (
              <EmptyState
                title="Проектов пока нет"
                text="Создайте проект или попросите владельца добавить вас по email."
              />
            ) : (
              <ul className={styles.list}>
                {data.projects.map((p) => (
                  <li key={p.id} className={styles.member}>
                    <span className={styles.name}>{p.name}</span>
                    <Badge tone="neutral">{roleLabel[p.role]}</Badge>
                    {p.id === data.current_project_id ? (
                      <Badge tone="success" icon={<Check size={12} />}>
                        текущий
                      </Badge>
                    ) : (
                      <Button size="sm" variant="secondary" onClick={() => void select(p.id)}>
                        Сделать текущим
                      </Button>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </section>
        ) : null}
        {current ? <Members projectId={current.id} myRole={current.role} /> : null}
        <CreateProject />
        <JoinProject />
      </main>
    </div>
  );
};
