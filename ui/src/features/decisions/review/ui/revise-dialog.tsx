import { useId, useState, type FormEvent, type RefObject } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import type { DecisionPlace, DecisionRow } from '@/entities/decision';
import { entryQueryOptions } from '@/entities/entry';
import { ApiError } from '@/shared/api';
import { errorMessage, fieldReasonText } from '@/shared/errors';
import { Button, Callout, Dialog, Input, QueryState, Textarea } from '@/shared/ui';
import { useReviseDecision } from '../model/use-review';

interface ReviseDialogProps {
  row: DecisionRow;
  place: DecisionPlace;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onDone: () => void;
  returnFocus: RefObject<HTMLElement | null>;
}

/**
 * Окно «Исправить»: название и текст прежнего решения, готовые к правке. Отправка создаёт
 * новое решение с `supersedes` прежнего; оно сразу подтверждено (TRK-755, п. 7).
 *
 * Текст решения в списке не приходит — он в записи дела, и форма появляется, когда запись
 * прочитана: пустое поле, которое человек принял бы за пустое решение, хуже короткого
 * ожидания.
 */
export function ReviseDialog({
  row,
  place,
  open,
  onOpenChange,
  onDone,
  returnFocus,
}: ReviseDialogProps) {
  const { t } = useTranslation('decisions');
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={t('revise.title', { ref: row.ref })}
      description={t('revise.intro')}
      closeLabel={t('close')}
      returnFocus={returnFocus}
    >
      <ReviseLoader
        row={row}
        place={place}
        onCancel={() => onOpenChange(false)}
        onDone={() => {
          onOpenChange(false);
          onDone();
        }}
      />
    </Dialog>
  );
}

function ReviseLoader({
  row,
  place,
  onCancel,
  onDone,
}: {
  row: DecisionRow;
  place: DecisionPlace;
  onCancel: () => void;
  onDone: () => void;
}) {
  const { t } = useTranslation('decisions');
  const entry = useQuery(entryQueryOptions(place.owner, place.no));
  if (entry.data === undefined || entry.data === null) {
    return <QueryState query={entry} loading={t('revise.bodyLoading')} />;
  }
  return (
    <ReviseForm
      place={place}
      initialTitle={row.title}
      initialBody={entry.data.body}
      onCancel={onCancel}
      onDone={onDone}
    />
  );
}

function ReviseForm({
  place,
  initialTitle,
  initialBody,
  onCancel,
  onDone,
}: {
  place: DecisionPlace;
  initialTitle: string;
  initialBody: string;
  onCancel: () => void;
  onDone: () => void;
}) {
  const { t } = useTranslation('decisions');
  const [title, setTitle] = useState(initialTitle);
  const [body, setBody] = useState(initialBody);
  const [emptyTitle, setEmptyTitle] = useState(false);
  const revise = useReviseDecision();
  const titleId = useId();
  const bodyId = useId();
  const fields = revise.error instanceof ApiError ? revise.error.fields : null;

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (title.trim() === '') {
      setEmptyTitle(true);
      return;
    }
    revise.mutate({ place, title: title.trim(), body }, { onSuccess: onDone });
  }

  return (
    <form className="flex flex-col gap-4" onSubmit={submit} noValidate>
      <div className="flex flex-col gap-1">
        <label className="text-meta text-muted" htmlFor={titleId}>
          {t('revise.titleLabel')}
        </label>
        <Input
          id={titleId}
          value={title}
          required
          onChange={(event) => {
            setTitle(event.target.value);
            if (event.target.value.trim() !== '') setEmptyTitle(false);
          }}
          aria-invalid={emptyTitle || fields?.title !== undefined}
        />
        {emptyTitle ? (
          <span className="text-meta text-danger" role="alert">
            {t('revise.titleEmpty')}
          </span>
        ) : fields?.title === undefined ? null : (
          <span className="text-meta text-danger" role="alert">
            {fieldReasonText(fields.title)}
          </span>
        )}
      </div>

      <div className="flex flex-col gap-1">
        <label className="text-meta text-muted" htmlFor={bodyId}>
          {t('revise.bodyLabel')}
        </label>
        <Textarea
          id={bodyId}
          rows={8}
          value={body}
          onChange={(event) => setBody(event.target.value)}
          aria-invalid={fields?.body !== undefined}
        />
        {fields?.body === undefined ? null : (
          <span className="text-meta text-danger" role="alert">
            {fieldReasonText(fields.body)}
          </span>
        )}
      </div>

      <div className="flex flex-wrap gap-2">
        <Button type="submit" disabled={revise.isPending}>
          {revise.isPending ? t('revise.pending') : t('revise.submit')}
        </Button>
        <Button tone="quiet" type="button" onClick={onCancel}>
          {t('cancel')}
        </Button>
      </div>

      {revise.isError ? (
        <Callout tone="danger">
          {errorMessage(revise.error)} {t('retrySafe')}
        </Callout>
      ) : null}
    </form>
  );
}
