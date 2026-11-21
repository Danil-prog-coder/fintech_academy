import { KeyRound, Save, Trash2 } from 'lucide-react';
import { useState } from 'react';

import { useGetSectionsQuery, type Section } from '@/entities/document';
import {
  useDeleteMemberMutation,
  useGetMembersQuery,
  usePasswordResetMutation,
  usePatchMemberMutation,
  type Member,
} from '@/entities/member';
import { roleLabel, useGetMeQuery } from '@/entities/session';
import { getErrorMessage } from '@/shared/api';
import {
  Badge,
  Button,
  Card,
  Checkbox,
  IconButton,
  layout,
  Notice,
  Select,
  Skeleton,
  TextField,
} from '@/shared/ui';
import { PanelLayout } from '@/widgets/panel-layout';

type Assignable = 'admin' | 'support' | 'user';

const MemberRow = ({
  m,
  sections,
  isOwner,
  self,
}: {
  m: Member;
  sections: Section[];
  isOwner: boolean;
  self: boolean;
}) => {
  const [role, setRole] = useState<Assignable>(m.role === 'owner' ? 'user' : m.role);
  const [login, setLogin] = useState('');
  const [restricted, setRestricted] = useState(m.allowed_sections !== null);
  const [allowed, setAllowed] = useState<string[]>(m.allowed_sections ?? []);
  const [patch, patchState] = usePatchMemberMutation();
  const [remove] = useDeleteMemberMutation();
  const [reset] = usePasswordResetMutation();
  const [note, setNote] = useState<string | null>(null);
  const editable = m.role !== 'owner' && !self && (isOwner || m.role === 'user');
  const roleOptions = (isOwner ? ['user', 'admin', 'support'] : ['user']).map((r) => ({
    value: r as Assignable,
    label: roleLabel[r] ?? r,
  }));
  const needsLogin = role !== 'user' && !m.panel_login;

  const save = () => {
    setNote(null);
    patch({
      externalId: m.external_id,
      body: {
        role,
        login: needsLogin ? login.trim() : undefined,
        allowed_sections: restricted ? allowed : null,
        set_sections: true,
      },
    })
      .unwrap()
      .then((r) => {
        setNote(
          r.panel_setup_url
            ? `Сохранено. Ссылка, чтобы задать пароль: ${r.panel_setup_url}`
            : 'Сохранено.',
        );
      })
      .catch((e: unknown) => {
        setNote(getErrorMessage(e));
      });
  };

  return (
    <li className={layout.item}>
      <div className={layout.stack}>
        <div className={layout.row}>
          <strong className={layout.grow}>{m.display_name ?? m.external_id}</strong>
          <Badge tone={m.role === 'user' ? 'neutral' : 'accent'}>{roleLabel[m.role]}</Badge>
          <span className={layout.muted}>id: {m.external_id}</span>
          {m.panel_login ? (
            <span className={layout.muted}>
              сайт: {m.panel_login}
              {m.panel_password_set ? '' : ' (пароль не задан)'}
            </span>
          ) : null}
          {isOwner && m.panel_login ? (
            <IconButton
              label="Ссылка для смены пароля"
              size="sm"
              icon={<KeyRound size={16} />}
              onClick={() => {
                reset(m.external_id)
                  .unwrap()
                  .then((r) => {
                    setNote(`Ссылка для пароля: ${r.panel_setup_url}`);
                  })
                  .catch((e: unknown) => {
                    setNote(getErrorMessage(e));
                  });
              }}
            />
          ) : null}
          {editable ? (
            <IconButton
              label="Удалить из проекта"
              size="sm"
              icon={<Trash2 size={16} />}
              onClick={() => void remove(m.external_id)}
            />
          ) : null}
        </div>
        {editable ? (
          <div className={layout.row}>
            <Select
              label="Статус"
              size="sm"
              value={role}
              options={roleOptions}
              onChange={setRole}
            />
            {needsLogin ? (
              <TextField
                label="Логин"
                placeholder="Логин на сайте"
                value={login}
                onChange={setLogin}
              />
            ) : null}
            {role !== 'admin' ? (
              <Checkbox
                checked={restricted}
                onChange={setRestricted}
                label="Только выбранные разделы"
              />
            ) : null}
            {restricted && role !== 'admin'
              ? sections.map((s) => (
                  <Checkbox
                    key={s.slug}
                    checked={allowed.includes(s.slug)}
                    label={s.title}
                    onChange={(on) => {
                      setAllowed((cur) =>
                        on ? [...cur, s.slug] : cur.filter((x) => x !== s.slug),
                      );
                    }}
                  />
                ))
              : null}
            <Button
              size="sm"
              icon={<Save size={16} />}
              disabled={patchState.isLoading || (needsLogin && login.trim().length < 3)}
              onClick={save}
            >
              Сохранить
            </Button>
          </div>
        ) : null}
        {note ? (
          <Notice tone="info" compact>
            {note}
          </Notice>
        ) : null}
      </div>
    </li>
  );
};

export const MembersPage = () => {
  const { data: me } = useGetMeQuery(undefined);
  const { data, error, isLoading } = useGetMembersQuery(undefined);
  const { data: sections } = useGetSectionsQuery(undefined);
  return (
    <PanelLayout title="Участники">
      <Notice tone="info">
        Участников регистрирует сервис, в который встроена платформа (почта, мессенджер, портал): он
        передаёт id своих пользователей. Здесь можно поменять статус и разделы. Админ управляет
        только пользователями; админов и поддержку назначает владелец.
      </Notice>
      {isLoading ? <Skeleton height={120} /> : null}
      {error ? <Notice tone="danger">{getErrorMessage(error)}</Notice> : null}
      <Card title={`Всего: ${String(data?.members.length ?? 0)}`}>
        <ul className={layout.list}>
          {data?.members.map((m) => (
            <MemberRow
              key={`${m.external_id}-${m.role}`}
              m={m}
              sections={sections?.sections ?? []}
              isOwner={me?.role === 'owner'}
              self={me?.external_id === m.external_id}
            />
          ))}
        </ul>
      </Card>
    </PanelLayout>
  );
};
