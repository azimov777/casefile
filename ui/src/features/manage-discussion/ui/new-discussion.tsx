import { useId, useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router';
import { Plus } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { bootstrapQueryOptions } from '@/entities/session';
import { ApiError } from '@/shared/api';
import { complainsAbout, errorMessage } from '@/shared/errors';
import { discussionHref } from '@/shared/lib';
import { Button, Callout, Dialog, Input, Textarea } from '@/shared/ui';
import { useCreateDiscussion } from '../model/use-discussion-actions';

/**
 * «Новое обсуждение»: человек заводит обсуждение сам, запиской, без вопроса, и привязывает
 * задачи (`TRK#51`, п. 8). Вопросом обсуждение заводит агент — через MCP; закрыть его
 * человек не может, и в форме этого нет.
 *
 * Название — сам узкий вопрос одной строкой; текст — контекст, он ложится первой записью
 * дела. Отправленное обсуждение открывается сразу: его заводят, чтобы вести.
 */
export function NewDiscussion({ project }: { project: string }) {
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const { t } = useTranslation('discussions');

  return (
    <Dialog
      open={open}
      onOpenChange={setOpen}
      title={t('create.title')}
      description={t('create.intro')}
      closeLabel={t('create.close')}
      trigger={
        <Button tone="quiet" size="sm">
          <Plus className="size-(--ui-mark)" aria-hidden="true" />
          {t('create.open')}
        </Button>
      }
    >
      <NewDiscussionForm
        project={project}
        onCancel={() => setOpen(false)}
        onCreated={(address) => {
          setOpen(false);
          void navigate(discussionHref(address));
        }}
      />
    </Dialog>
  );
}

/** Форма окна: рождается заново при каждом открытии, прошлый отказ в неё не переезжает. */
function NewDiscussionForm({
  project,
  onCancel,
  onCreated,
}: {
  project: string;
  onCancel: () => void;
  onCreated: (address: string) => void;
}) {
  const bootstrap = useQuery(bootstrapQueryOptions());
  const projects = bootstrap.data?.projects ?? [];
  const [chosen, setChosen] = useState(project);
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [tasks, setTasks] = useState('');
  const [problem, setProblem] = useState<'title' | 'project' | null>(null);
  const [idempotencyKey] = useState(() => crypto.randomUUID());
  const create = useCreateDiscussion();
  const projectId = useId();
  const titleId = useId();
  const bodyId = useId();
  const tasksId = useId();
  const { t } = useTranslation('discussions');

  // Проект: названный отбором входящей или единственный в установке; иначе выбирают.
  const effective = chosen !== '' ? chosen : projects.length === 1 ? (projects[0]?.key ?? '') : '';
  const badTitle = complainsAbout(create.error, 'title');
  const taskRefused =
    create.error instanceof ApiError && create.error.code === 'task_closed'
      ? errorMessage(create.error)
      : null;

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (effective === '') {
      setProblem('project');
      return;
    }
    if (title.trim() === '') {
      setProblem('title');
      return;
    }
    setProblem(null);
    create.mutate(
      {
        project: effective,
        title: title.trim().replace(/\s+/g, ' '),
        body: body.trim(),
        tasks: tasks
          .split(/[\s,;]+/)
          .map((key) => key.trim())
          .filter((key) => key !== ''),
        idempotencyKey,
      },
      { onSuccess: (discussion) => onCreated(discussion.address) },
    );
  }

  return (
    <form className="flex flex-col gap-4" onSubmit={submit} noValidate>
      <div className="flex flex-col gap-1">
        <label className="text-meta text-muted" htmlFor={projectId}>
          {t('create.projectLabel')}
        </label>
        <select
          id={projectId}
          className="max-w-full truncate rounded-mark border border-line-strong bg-surface px-2 py-2 text-text aria-invalid:border-danger"
          value={effective}
          onChange={(event) => {
            setChosen(event.target.value);
            setProblem(null);
          }}
          aria-invalid={problem === 'project'}
        >
          <option value="">{t('create.projectChoose')}</option>
          {projects.map((item) => (
            <option key={item.key} value={item.key}>
              {item.key} — {item.title}
            </option>
          ))}
        </select>
        {problem === 'project' ? (
          <span className="text-meta text-danger" role="alert">
            {t('create.projectEmpty')}
          </span>
        ) : null}
      </div>

      <div className="flex flex-col gap-1">
        <label className="text-meta text-muted" htmlFor={titleId}>
          {t('create.titleLabel')}
        </label>
        <Input
          id={titleId}
          value={title}
          onChange={(event) => {
            setTitle(event.target.value);
            setProblem(null);
          }}
          autoComplete="off"
          aria-invalid={problem === 'title' || badTitle}
        />
        <span className="text-meta text-muted">{t('create.titleHint')}</span>
        {problem === 'title' ? (
          <span className="text-meta text-danger" role="alert">
            {t('create.titleEmpty')}
          </span>
        ) : null}
      </div>

      <div className="flex flex-col gap-1">
        <label className="text-meta text-muted" htmlFor={bodyId}>
          {t('create.bodyLabel')}
        </label>
        <Textarea id={bodyId} rows={4} value={body} onChange={(e) => setBody(e.target.value)} />
      </div>

      <div className="flex flex-col gap-1">
        <label className="text-meta text-muted" htmlFor={tasksId}>
          {t('create.tasksLabel')}
        </label>
        <Input
          id={tasksId}
          className="font-mono"
          value={tasks}
          onChange={(event) => setTasks(event.target.value)}
          autoComplete="off"
          autoCapitalize="characters"
          spellCheck={false}
          placeholder={t('create.tasksPlaceholder')}
        />
        <span className="text-meta text-muted">{t('create.tasksHint')}</span>
      </div>

      {/* Кнопки выше всего изменчивого: отказ, выросший над ними, увёл бы их из-под пальца. */}
      <div className="flex flex-wrap gap-2">
        <Button type="submit" disabled={create.isPending}>
          {create.isPending ? t('create.pending') : t('create.submit')}
        </Button>
        <Button tone="quiet" onClick={onCancel}>
          {t('create.cancel')}
        </Button>
      </div>

      {create.isError ? (
        <Callout tone="danger">
          {taskRefused ?? errorMessage(create.error)} {t('retrySafe')}
        </Callout>
      ) : null}
    </form>
  );
}
