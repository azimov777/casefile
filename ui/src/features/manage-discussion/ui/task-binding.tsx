import { useId, useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { Unlink } from 'lucide-react';
import { errorMessage } from '@/shared/errors';
import { Button, Callout, Input } from '@/shared/ui';
import { useAttachTask, useDetachTask } from '../model/use-discussion-actions';

/**
 * «Привязать»: ключ задачи, которая зависит от итога обсуждения (`TRK#51`, п. 3).
 *
 * Привязывает и человек, и агент. Закрытая задача и закрытое обсуждение отказываются
 * бэкендом (`task_closed`, `discussion_closed`), и отказ сказан словами под полем — формы
 * для закрытого обсуждения экран не показывает вовсе.
 */
export function AttachTaskForm({ address }: { address: string }) {
  const attach = useAttachTask(address);
  const [task, setTask] = useState('');
  const [empty, setEmpty] = useState(false);
  const fieldId = useId();
  const { t } = useTranslation('discussions');

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const key = task.trim();
    if (key === '') {
      setEmpty(true);
      return;
    }
    setEmpty(false);
    attach.mutate(
      { task: key, idempotencyKey: crypto.randomUUID() },
      { onSuccess: () => setTask('') },
    );
  }

  return (
    <form
      className="flex flex-col gap-2"
      onSubmit={submit}
      aria-label={t('attach.formLabel', { address })}
      noValidate
    >
      <label className="text-meta text-muted" htmlFor={fieldId}>
        {t('attach.fieldLabel')}
      </label>
      <div className="flex flex-wrap gap-2">
        <Input
          id={fieldId}
          className="min-w-0 flex-1 basis-40 font-mono"
          value={task}
          onChange={(event) => {
            setTask(event.target.value);
            setEmpty(false);
          }}
          autoComplete="off"
          autoCapitalize="characters"
          spellCheck={false}
          placeholder={t('attach.placeholder')}
          aria-invalid={empty || attach.isError}
        />
        <Button type="submit" disabled={attach.isPending}>
          {attach.isPending ? t('attach.pending') : t('attach.submit')}
        </Button>
      </div>
      {empty ? (
        <span className="text-meta text-danger" role="alert">
          {t('attach.empty')}
        </span>
      ) : null}
      {attach.isError ? <Callout tone="danger">{errorMessage(attach.error)}</Callout> : null}
    </form>
  );
}

/** «Отвязать» у привязанной задачи: итог её больше не держит. */
export function DetachTaskButton({ address, taskKey }: { address: string; taskKey: string }) {
  const detach = useDetachTask(address);
  const { t } = useTranslation('discussions');

  return (
    <span className="inline-flex flex-wrap items-center gap-2">
      <Button
        tone="quiet"
        size="sm"
        disabled={detach.isPending}
        aria-label={t('detach.label', { key: taskKey })}
        onClick={() => detach.mutate({ task: taskKey })}
      >
        <Unlink className="size-(--ui-mark)" aria-hidden="true" />
        {t('detach.submit')}
      </Button>
      {detach.isError ? (
        <span className="text-meta text-danger" role="alert">
          {errorMessage(detach.error)}
        </span>
      ) : null}
    </span>
  );
}
