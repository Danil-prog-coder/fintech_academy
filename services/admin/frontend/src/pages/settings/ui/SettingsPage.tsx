import { Eye, PlugZap, RefreshCw, Save } from 'lucide-react';
import { useState } from 'react';

import {
  useCheckJiraMutation,
  useGetJiraQuery,
  useGetProjectCodeQuery,
  usePutJiraMutation,
  useRotateJiraSecretMutation,
  useRotateProjectCodeMutation,
  type JiraSettings,
} from '@/entities/setting';
import { getErrorMessage } from '@/shared/api';
import { Button, Card, Checkbox, layout, Notice, TextField } from '@/shared/ui';
import { PanelLayout } from '@/widgets/panel-layout';

const ProjectCode = () => {
  const [shown, setShown] = useState(false);
  const { data } = useGetProjectCodeQuery(undefined, { skip: !shown });
  const [rotate, rotateState] = useRotateProjectCodeMutation();
  const code = rotateState.data?.code ?? data?.code;
  return (
    <Card title="Код проекта">
      <p className={layout.muted}>
        Код нужен для входа на этот сайт (вместе с логином и паролем) и для замены раздела
        документации. После смены кода старый перестаёт работать сразу — передайте новый админам и
        поддержке.
      </p>
      <div className={layout.row}>
        {code ? <code className={layout.code}>{code}</code> : null}
        {!shown ? (
          <Button
            size="sm"
            icon={<Eye size={16} />}
            onClick={() => {
              setShown(true);
            }}
          >
            Показать
          </Button>
        ) : null}
        <Button
          size="sm"
          icon={<RefreshCw size={16} />}
          disabled={rotateState.isLoading}
          onClick={() => void rotate(undefined)}
        >
          Выпустить новый
        </Button>
      </div>
    </Card>
  );
};

const JiraForm = ({ current }: { current: JiraSettings }) => {
  const [baseUrl, setBaseUrl] = useState(current.base_url ?? 'https://');
  const [email, setEmail] = useState(current.email ?? '');
  const [token, setToken] = useState('');
  const [projectKey, setProjectKey] = useState(current.project_key ?? '');
  const [issueType, setIssueType] = useState(current.issue_type ?? 'Task');
  const [enabled, setEnabled] = useState(current.enabled ?? true);
  const [put, putState] = usePutJiraMutation();
  const [check, checkState] = useCheckJiraMutation();
  const [rotate, rotateState] = useRotateJiraSecretMutation();
  const secret = putState.data?.webhook_secret ?? rotateState.data?.webhook_secret;
  return (
    <Card title="Jira для поддержки">
      <p className={layout.muted}>
        Обращения в поддержку дублируются задачами в Jira: ответы специалистов из Jira доходят до
        пользователя, а закрытие задачи закрывает обращение.
      </p>
      <div className={layout.row}>
        <TextField
          label="Адрес Jira"
          placeholder="https://company.atlassian.net"
          value={baseUrl}
          onChange={setBaseUrl}
        />
        <TextField
          label="Email"
          placeholder="Email учётной записи Jira"
          value={email}
          onChange={setEmail}
        />
        <TextField
          label="API-токен"
          placeholder={current.configured ? 'API-токен (пусто — оставить прежний)' : 'API-токен'}
          type="password"
          value={token}
          onChange={setToken}
        />
        <TextField
          label="Ключ проекта"
          placeholder="Ключ проекта Jira, например SUP"
          value={projectKey}
          onChange={setProjectKey}
        />
        <TextField
          label="Тип задачи"
          placeholder="Тип задачи"
          value={issueType}
          onChange={setIssueType}
        />
        <Checkbox checked={enabled} onChange={setEnabled} label="Включено" />
      </div>
      <div className={layout.row}>
        <Button
          variant="primary"
          size="sm"
          icon={<Save size={16} />}
          disabled={
            putState.isLoading ||
            !baseUrl ||
            !email ||
            !projectKey ||
            (!current.configured && !token)
          }
          onClick={() =>
            void put({
              base_url: baseUrl.trim(),
              email: email.trim(),
              api_token: token || undefined,
              project_key: projectKey.trim(),
              issue_type: issueType.trim(),
              enabled,
            })
          }
        >
          Сохранить
        </Button>
        {current.configured ? (
          <>
            <Button
              size="sm"
              icon={<PlugZap size={16} />}
              disabled={checkState.isLoading}
              onClick={() => void check(undefined)}
            >
              Проверить подключение
            </Button>
            <Button size="sm" icon={<RefreshCw size={16} />} onClick={() => void rotate(undefined)}>
              Новый секрет вебхука
            </Button>
          </>
        ) : null}
      </div>
      {putState.error ? <Notice tone="danger">{getErrorMessage(putState.error)}</Notice> : null}
      {checkState.data ? (
        <Notice tone={checkState.data.ok ? 'success' : 'danger'} compact>
          {checkState.data.ok
            ? `Подключено: ${checkState.data.project?.name ?? ''}`
            : `Ошибка: ${checkState.data.error ?? ''}`}
        </Notice>
      ) : null}
      {current.webhook_url ? (
        <Notice tone="info" title="Вебхук в Jira">
          В Jira → Settings → System → WebHooks создайте вебхук на{' '}
          <code className={layout.code}>{current.webhook_url}</code> для событий «comment created» и
          «issue updated» с этим секретом.
          {secret ? (
            <>
              {' '}
              Секрет (показывается один раз): <code className={layout.code}>{secret}</code>
            </>
          ) : null}
        </Notice>
      ) : null}
    </Card>
  );
};

export const SettingsPage = () => {
  const { data } = useGetJiraQuery(undefined);
  return (
    <PanelLayout title="Настройки проекта">
      <ProjectCode />
      {data ? <JiraForm key={String(data.configured)} current={data} /> : null}
    </PanelLayout>
  );
};
