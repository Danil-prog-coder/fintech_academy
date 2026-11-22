import { Link2 } from 'lucide-react';
import { useState } from 'react';
import { useSearchParams } from 'react-router';

import {
  roleLabel,
  useClaimInviteMutation,
  useEnterProject,
  useGetInviteQuery,
  useGetMeQuery,
  type Invite,
} from '@/entities/session';
import { AuthForm } from '@/features/site-auth';
import { getErrorMessage } from '@/shared/api';
import { Button, Card, layout, Logo, Notice, Spinner } from '@/shared/ui';

interface ClaimProps {
  token: string;
  invite: Invite;
}

/** Нет входа: регистрация (логин подсказан из ссылки) или вход в существующий аккаунт, затем привязка. */
const SignInAndClaim = ({ token, invite }: ClaimProps) => {
  const [mode, setMode] = useState<'register' | 'login'>('register');
  const [claim, { error }] = useClaimInviteMutation();
  const enterProject = useEnterProject();
  return (
    <>
      <AuthForm
        key={mode}
        mode={mode}
        defaultLogin={mode === 'register' ? invite.login_hint : ''}
        onDone={() => {
          void claim({ token })
            .unwrap()
            .then(enterProject)
            .catch(() => undefined);
        }}
      />
      {error ? <Notice tone="danger">{getErrorMessage(error)}</Notice> : null}
      <p className={layout.muted}>
        {mode === 'register' ? 'Уже есть аккаунт на этом сайте? ' : 'Нет аккаунта? '}
        <Button
          variant="link"
          size="sm"
          onClick={() => {
            setMode(mode === 'register' ? 'login' : 'register');
          }}
        >
          {mode === 'register' ? 'Войдите в него' : 'Зарегистрируйтесь'}
        </Button>
      </p>
    </>
  );
};

const ClaimSignedIn = ({ token, login }: { token: string; login: string }) => {
  const [claim, { isLoading, error }] = useClaimInviteMutation();
  const enterProject = useEnterProject();
  return (
    <>
      <Button
        variant="primary"
        icon={<Link2 size={18} />}
        disabled={isLoading}
        onClick={() => {
          void claim({ token })
            .unwrap()
            .then(enterProject)
            .catch(() => undefined);
        }}
      >
        Добавить к аккаунту {login}
      </Button>
      {error ? <Notice tone="danger">{getErrorMessage(error)}</Notice> : null}
    </>
  );
};

/** Вошёл человек или нет — решается один раз при открытии: после входа запрос /me обновится, а форма не должна мигать. */
const ClaimFlow = ({ token, invite, login }: ClaimProps & { login: string | null }) => {
  const [signedInAs] = useState(login);
  return signedInAs ? (
    <ClaimSignedIn token={token} login={signedInAs} />
  ) : (
    <SignInAndClaim token={token} invite={invite} />
  );
};

/** Одноразовая ссылка от интеграции: статус в проекте привязывается к аккаунту сайта. */
export const SetupPage = () => {
  const [params] = useSearchParams();
  const token = params.get('token') ?? '';
  const invite = useGetInviteQuery(token, { skip: !token });
  const me = useGetMeQuery(undefined);

  let content;
  if (!token) {
    content = <Notice tone="danger">В ссылке нет токена — откройте ссылку целиком.</Notice>;
  } else if (invite.isLoading || me.isLoading) {
    content = <Spinner label="Проверяем ссылку" />;
  } else if (invite.error || !invite.data) {
    content = <Notice tone="danger">{getErrorMessage(invite.error)}</Notice>;
  } else {
    content = (
      <>
        <Notice tone="info" title={`Проект «${invite.data.project.name}»`}>
          Вам назначен статус «{roleLabel[invite.data.role]}». Доступ к проекту добавится к вашему
          аккаунту на этом сайте.
        </Notice>
        <ClaimFlow token={token} invite={invite.data} login={me.data?.login ?? null} />
      </>
    );
  }

  return (
    <div className={layout.center}>
      <div className={layout.narrow}>
        <Card>
          <Logo caption="Доступ к проекту" />
          {content}
        </Card>
      </div>
    </div>
  );
};
