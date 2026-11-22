import { FolderPlus, RefreshCw, RotateCcw, Trash2, Upload } from 'lucide-react';
import { useState } from 'react';

import {
  useAddSectionMutation,
  useDeleteDocumentMutation,
  useDeleteSectionMutation,
  useGetDocumentsQuery,
  useGetJobsQuery,
  useGetSectionsQuery,
  useReindexMutation,
  useRollbackMutation,
  useUploadDocumentsMutation,
} from '@/entities/document';
import { getErrorMessage } from '@/shared/api';
import {
  Badge,
  Button,
  Card,
  IconButton,
  layout,
  Notice,
  Select,
  Skeleton,
  TextField,
} from '@/shared/ui';
import { PanelLayout } from '@/widgets/panel-layout';

const jobStatus: Record<string, string> = {
  queued: 'в очереди',
  running: 'идёт',
  done: 'готово',
  failed: 'ошибка',
  interrupted: 'прервано',
};

const Sections = () => {
  const { data } = useGetSectionsQuery(undefined);
  const [add, addState] = useAddSectionMutation();
  const [remove] = useDeleteSectionMutation();
  const [slug, setSlug] = useState('');
  const [title, setTitle] = useState('');
  const [error, setError] = useState<string | null>(null);
  return (
    <Card title="Разделы">
      <p className={layout.muted}>
        Раздел — часть документации, которую можно открыть не всем: у участника можно ограничить
        список разделов.
      </p>
      <ul className={layout.list}>
        {data?.sections.map((s) => (
          <li key={s.slug} className={layout.item}>
            <span className={layout.grow}>
              {s.title} <span className={layout.muted}>({s.slug})</span>
            </span>
            {s.slug !== 'general' ? (
              <IconButton
                label={`Удалить раздел ${s.title}`}
                size="sm"
                icon={<Trash2 size={16} />}
                onClick={() => {
                  setError(null);
                  remove(s.slug)
                    .unwrap()
                    .catch((e: unknown) => {
                      setError(getErrorMessage(e));
                    });
                }}
              />
            ) : null}
          </li>
        ))}
      </ul>
      <form
        className={layout.row}
        onSubmit={(event) => {
          event.preventDefault();
          setError(null);
          add({ slug: slug.trim(), title: title.trim() })
            .unwrap()
            .then(() => {
              setSlug('');
              setTitle('');
            })
            .catch((e: unknown) => {
              setError(getErrorMessage(e));
            });
        }}
      >
        <TextField
          label="Название"
          placeholder="Название, например «Безопасность»"
          value={title}
          onChange={setTitle}
        />
        <TextField
          label="Код"
          placeholder="Код латиницей: security"
          value={slug}
          onChange={setSlug}
        />
        <Button
          type="submit"
          icon={<FolderPlus size={16} />}
          disabled={addState.isLoading || !slug || !title}
        >
          Добавить раздел
        </Button>
      </form>
      {error ? <Notice tone="danger">{error}</Notice> : null}
    </Card>
  );
};

export const DocumentsPage = () => {
  const docs = useGetDocumentsQuery(undefined, {
    pollingInterval: 10000,
    skipPollingIfUnfocused: true,
  });
  const jobs = useGetJobsQuery(undefined, { pollingInterval: 5000, skipPollingIfUnfocused: true });
  const { data: sections } = useGetSectionsQuery(undefined);
  const [upload, uploadState] = useUploadDocumentsMutation();
  const [remove] = useDeleteDocumentMutation();
  const [reindex] = useReindexMutation();
  const [rollback] = useRollbackMutation();
  const [files, setFiles] = useState<File[]>([]);
  const [section, setSection] = useState('general');
  const [mode, setMode] = useState<'append' | 'replace'>('append');
  const [code, setCode] = useState('');
  const [note, setNote] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null);
  const sectionOptions = (sections?.sections ?? [{ slug: 'general', title: 'Общее' }]).map((s) => ({
    value: s.slug,
    label: s.title,
  }));

  const run = (p: Promise<unknown>, ok: string) => {
    setNote(null);
    p.then(() => {
      setNote({ tone: 'success', text: ok });
    }).catch((e: unknown) => {
      setNote({ tone: 'danger', text: getErrorMessage(e) });
    });
  };

  const submit = () => {
    const form = new FormData();
    files.forEach((f) => {
      form.append('files', f);
    });
    form.append('section', section);
    form.append('mode', mode);
    if (mode === 'replace') {
      form.append('project_code', code);
    }
    run(
      upload(form)
        .unwrap()
        .then(() => {
          setFiles([]);
          setCode('');
        }),
      'Файлы загружены, индексация запущена. Пользователи получат уведомление, когда новая версия будет опубликована.',
    );
  };

  return (
    <PanelLayout title="Документация">
      <Card title="Загрузить документы">
        <div className={layout.row}>
          <input
            type="file"
            multiple
            accept=".docx,.pdf,.md,.markdown,.txt"
            aria-label="Файлы документации"
            onChange={(event) => {
              setFiles(Array.from(event.target.files ?? []));
            }}
          />
          <Select label="Раздел" value={section} options={sectionOptions} onChange={setSection} />
          <Select
            label="Режим"
            value={mode}
            options={[
              { value: 'append', label: 'Дополнить раздел' },
              { value: 'replace', label: 'Заменить раздел' },
            ]}
            onChange={setMode}
          />
          {mode === 'replace' ? (
            <TextField
              label="Код проекта"
              placeholder="Код проекта для подтверждения"
              value={code}
              onChange={setCode}
            />
          ) : null}
          <Button
            variant="primary"
            icon={<Upload size={16} />}
            disabled={uploadState.isLoading || files.length === 0 || (mode === 'replace' && !code)}
            onClick={submit}
          >
            Загрузить
          </Button>
        </div>
        <p className={layout.muted}>
          Форматы: .docx, .pdf, .md, .txt. Картинки из документов описывает ИИ, ответы прикладывают
          их к тексту.
        </p>
        {note ? <Notice tone={note.tone}>{note.text}</Notice> : null}
      </Card>
      <Card
        title="Опубликованная версия"
        actions={
          <>
            <Button
              size="sm"
              icon={<RefreshCw size={16} />}
              onClick={() => {
                run(reindex(undefined).unwrap(), 'Переиндексация запущена.');
              }}
            >
              Переиндексировать
            </Button>
            <Button
              size="sm"
              icon={<RotateCcw size={16} />}
              onClick={() => {
                run(rollback(undefined).unwrap(), 'Восстановлена предыдущая версия базы.');
              }}
            >
              Откатить версию
            </Button>
          </>
        }
      >
        {docs.isLoading ? <Skeleton height={80} /> : null}
        {docs.error ? <Notice tone="danger">{getErrorMessage(docs.error)}</Notice> : null}
        {docs.data?.published.documents.length === 0 ? (
          <p className={layout.muted}>Документов пока нет.</p>
        ) : null}
        <ul className={layout.list}>
          {docs.data?.published.documents.map((d) => (
            <li key={d.doc_id} className={layout.item}>
              <span className={layout.grow}>{d.title}</span>
              <Badge tone="neutral">{d.section}</Badge>
              {d.chunks !== undefined ? (
                <span className={layout.muted}>{d.chunks} фрагм.</span>
              ) : null}
              <IconButton
                label={`Удалить ${d.title}`}
                size="sm"
                icon={<Trash2 size={16} />}
                onClick={() => {
                  run(remove(d.doc_id).unwrap(), 'Документ удалён, база пересобирается.');
                }}
              />
            </li>
          ))}
        </ul>
      </Card>
      <Sections />
      <Card title="Задачи индексации">
        <ul className={layout.list}>
          {jobs.data?.jobs.slice(0, 8).map((j) => (
            <li key={j.job_id} className={layout.item}>
              <span className={layout.grow}>{j.kind}</span>
              <Badge
                tone={
                  j.status === 'done' ? 'success' : j.status === 'failed' ? 'danger' : 'warning'
                }
              >
                {jobStatus[j.status] ?? j.status}
              </Badge>
              <span className={layout.muted}>
                {new Date(j.created_at * 1000).toLocaleString('ru-RU')}
              </span>
              {j.error ? <span className={layout.muted}>{j.error}</span> : null}
            </li>
          ))}
        </ul>
      </Card>
    </PanelLayout>
  );
};
