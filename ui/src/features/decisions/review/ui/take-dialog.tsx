import { useId, useState, type FormEvent, type RefObject } from 'react';
import { useTranslation } from 'react-i18next';
import type { DecisionPlace, DecisionRow } from '@/entities/decision';
import { errorMessage } from '@/shared/errors';
import { Button, Callout, Dialog, Textarea } from '@/shared/ui';
import { useReviewDecision } from '../model/use-review';

/** Исходы, что выводят решение из силы без замены. */
export type TakeOutcome = 'rejected' | 'removed';

interface TakeDialogProps {
  row: DecisionRow;
  place: DecisionPlace;
  outcome: TakeOutcome;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Проверка записана: окно закрыто, список перечитывается. */
  onDone: () => void;
  returnFocus: RefObject<HTMLElement | null>;
}

/**
 * Окно «Отклонить» и окно «Удалить»: решение выходит из силы без замены, запись остаётся
 * в деле (TRK-755). Два исхода различаются только пометой в истории — «не согласен» и
 * «устарело», — поэтому окно одно. Причина необязательна.
 *
 * Спрашивает ролью `alertdialog` и называет две вещи, о которых человек иначе узнал бы
 * после: решение, которое отклонённое когда-то заменило, не вернётся, и число задач,
 * что на нём стоят.
 */
export function TakeDialog({
  row,
  place,
  outcome,
  open,
  onOpenChange,
  onDone,
  returnFocus,
}: TakeDialogProps) {
  const { t } = useTranslation('decisions');
  return (
    <Dialog
      alert
      open={open}
      onOpenChange={onOpenChange}
      title={t(`take.${outcome === 'rejected' ? 'reject' : 'remove'}.title`, { ref: row.ref })}
      description={t(`take.${outcome === 'rejected' ? 'reject' : 'remove'}.intro`)}
      closeLabel={t('close')}
      returnFocus={returnFocus}
    >
      <TakeForm
        row={row}
        place={place}
        outcome={outcome}
        onCancel={() => onOpenChange(false)}
        onDone={() => {
          onOpenChange(false);
          onDone();
        }}
      />
    </Dialog>
  );
}

/** Форма окна рождается заново при каждом открытии: прошлая причина и отказ не переезжают. */
function TakeForm({
  row,
  place,
  outcome,
  onCancel,
  onDone,
}: {
  row: DecisionRow;
  place: DecisionPlace;
  outcome: TakeOutcome;
  onCancel: () => void;
  onDone: () => void;
}) {
  const { t } = useTranslation('decisions');
  const [reason, setReason] = useState('');
  const review = useReviewDecision();
  const reasonId = useId();
  const hintId = useId();

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    review.mutate({ place, outcome, reason: reason.trim() }, { onSuccess: onDone });
  }

  return (
    <form className="flex flex-col gap-4" onSubmit={submit} noValidate>
      {row.supersedes.length === 0 ? null : (
        <Callout>
          {t(row.supersedes.length === 1 ? 'take.replacedOne' : 'take.replacedMany', {
            refs: row.supersedes.join(', '),
          })}
        </Callout>
      )}
      {row.tasks === 0 ? null : (
        <p className="text-meta">{t('take.tasks', { count: row.tasks })}</p>
      )}

      <div className="flex flex-col gap-1">
        <label className="text-meta text-muted" htmlFor={reasonId}>
          {t('take.reasonLabel')}
        </label>
        <Textarea
          id={reasonId}
          rows={3}
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          aria-describedby={hintId}
        />
        <span className="text-meta text-muted" id={hintId}>
          {t('take.reasonHint')}
        </span>
      </div>

      <div className="flex flex-wrap gap-2">
        <Button type="submit" disabled={review.isPending}>
          {review.isPending
            ? t('action.pending')
            : t(`take.${outcome === 'rejected' ? 'reject' : 'remove'}.submit`)}
        </Button>
        <Button tone="quiet" type="button" onClick={onCancel}>
          {t('cancel')}
        </Button>
      </div>

      {review.isError ? (
        <Callout tone="danger">
          {errorMessage(review.error)} {t('retrySafe')}
        </Callout>
      ) : null}
    </form>
  );
}
