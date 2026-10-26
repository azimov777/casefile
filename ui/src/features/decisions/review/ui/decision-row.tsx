import { useId, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router';
import { useQuery } from '@tanstack/react-query';
import { decisionHref, parseDecisionRef, type DecisionRow } from '@/entities/decision';
import { AuthorName, DecisionStatusMark, entryQueryOptions } from '@/entities/entry';
import { errorMessage } from '@/shared/errors';
import { areaHref } from '@/shared/lib';
import { Badge, Button, Callout, Markdown, RelativeTime, TaskText } from '@/shared/ui';
import { useReviewDecision } from '../model/use-review';
import { ReviseDialog } from './revise-dialog';
import { TakeDialog, type TakeOutcome } from './take-dialog';

/** Строка решения: поля как у строки атрибута, линия между строками. */
const ROW = 'flex flex-col gap-1 border-b border-b-line px-3 py-2 last:border-b-0';

/** Ссылка на запись решения: ключ контракта моноширинным, целиком на одной строке. */
const REF = 'font-mono whitespace-nowrap';

interface DecisionReviewRowProps {
  row: DecisionRow;
  /**
   * Показывать ли действия проверки. Решает место вызова: архивный проект только читается,
   * и кнопка, что кончается отказом `project_archived`, не показывается вовсе.
   */
  canReview: boolean;
  /** Проверка записана — родитель возвращает фокус, а список перечитывается. */
  onReviewed: (ref: string) => void;
  /**
   * Адрес списка задач, стоящих на решении. Строит его место вызова: список задач — срез
   * `task-filters`, а срезы одного слоя друг друга не импортируют.
   */
  tasksHref: (ref: string) => string;
}

/**
 * Строка решения со всем, что нужно, чтобы его проверить (TRK-758, TRK-755): ссылка на
 * запись, название, метка «подтверждено» или «не подтверждено» (у снятого — «заменено»,
 * «отклонено», «удалено»), область, автор, время, число задач на решении и «откуда» —
 * ссылки `refs` решения. Раскрытая строка читает тело решения и у действующего решения
 * предлагает четыре действия: «Подтвердить» сразу, без окна; «Исправить» — форма с
 * текущим текстом; «Отклонить» и «Удалить» — окно с необязательной причиной.
 *
 * Все признаки — готовые поля строки от бэкенда (`status`, `review_state`, `tasks`):
 * строка их показывает и ничего не вычисляет (TRK#244). Одну эту строку берёт и Входящая
 * (TRK-759): модуль лежит в `features`, чтобы страницы не импортировали друг друга.
 */
export function DecisionReviewRow({
  row,
  canReview,
  onReviewed,
  tasksHref,
}: DecisionReviewRowProps) {
  const { t } = useTranslation('decisions');
  const place = parseDecisionRef(row.ref);
  const [open, setOpen] = useState(false);
  const bodyId = useId();
  const inForce = row.status === 'in_force';
  const href = decisionHref(row.ref);
  const successor = row.superseded_by === null ? null : decisionHref(row.superseded_by);

  return (
    <li
      className={ROW}
      data-decision={row.ref}
      data-status={row.status}
      data-review={inForce ? row.review_state : undefined}
    >
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        {href === null ? (
          <span className={REF}>{row.ref}</span>
        ) : (
          <Link to={href} className={REF}>
            {row.ref}
          </Link>
        )}
        {inForce ? (
          <ReviewMark state={row.review_state} />
        ) : (
          <DecisionStatusMark status={row.status} />
        )}
      </div>

      {/* Название — кнопка раскрытия: тело решения читается тут же, под строкой. */}
      <button
        type="button"
        className={`cursor-pointer border-none bg-transparent p-0 text-left wrap-anywhere hover:underline max-fold:min-h-(--ui-tap) before:content-['▸_'] aria-expanded:before:content-['▾_'] ${
          inForce ? '' : 'text-muted line-through'
        }`}
        aria-expanded={open}
        aria-controls={open ? bodyId : undefined}
        onClick={() => setOpen((value) => !value)}
      >
        {row.title}
      </button>

      <p className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-meta text-muted">
        {row.area === null ? (
          <span>{t('row.project')}</span>
        ) : (
          <span>
            {t('row.area')}{' '}
            <Link to={areaHref(row.area)} className={REF}>
              {row.area}
            </Link>
          </span>
        )}
        <AuthorName author={row.author} />
        <RelativeTime value={row.created_at} />
        {row.tasks === 0 ? (
          <span>{t('row.noTasks')}</span>
        ) : (
          <Link to={tasksHref(row.ref)}>{t('row.tasks', { count: row.tasks })}</Link>
        )}
      </p>

      {row.refs.length === 0 ? null : (
        <p className="text-meta wrap-anywhere text-muted" data-refs>
          {t('row.from')}: <TaskText>{row.refs.join(', ')}</TaskText>
        </p>
      )}

      {successor === null || row.superseded_by === null ? null : (
        <p className="text-meta">
          {t('row.supersededBy')}{' '}
          <Link to={successor} className={REF}>
            {row.superseded_by}
          </Link>
        </p>
      )}

      {open && place !== null ? (
        <div id={bodyId} className="flex flex-col gap-3 border-l-2 border-l-line pl-3">
          <DecisionBody place={place} />
          {inForce && canReview ? (
            <ReviewActions row={row} onReviewed={() => onReviewed(row.ref)} />
          ) : null}
        </div>
      ) : null}
    </li>
  );
}

/** Метка «подтверждено» / «не подтверждено» действующего решения. */
function ReviewMark({ state }: { state: DecisionRow['review_state'] }) {
  const { t } = useTranslation('decisions');
  return (
    <Badge tone={state === 'confirmed' ? 'positive' : 'attention'}>{t(`mark.${state}`)}</Badge>
  );
}

/** Тело решения: запись дела читается при раскрытии и живёт в кэше. */
function DecisionBody({ place }: { place: NonNullable<ReturnType<typeof parseDecisionRef>> }) {
  const { t } = useTranslation('decisions');
  const entry = useQuery(entryQueryOptions(place.owner, place.no));

  if (entry.data === undefined) {
    return entry.isError ? (
      <Callout tone="danger">{errorMessage(entry.error)}</Callout>
    ) : (
      <p className="text-meta text-muted">{t('row.bodyLoading')}</p>
    );
  }
  if (entry.data === null || entry.data.body.trim() === '') {
    return <p className="text-meta text-muted italic">{t('row.bodyEmpty')}</p>;
  }
  return (
    <div className="max-w-(--ui-text-max)">
      <Markdown>{entry.data.body}</Markdown>
    </div>
  );
}

/** Четыре действия над действующим решением; у подтверждённого «Подтвердить» нет. */
function ReviewActions({ row, onReviewed }: { row: DecisionRow; onReviewed: () => void }) {
  const { t } = useTranslation('decisions');
  const place = parseDecisionRef(row.ref);
  const [dialog, setDialog] = useState<'revise' | TakeOutcome | null>(null);
  const confirm = useReviewDecision();
  const reviseButton = useRef<HTMLButtonElement>(null);
  const rejectButton = useRef<HTMLButtonElement>(null);
  const removeButton = useRef<HTMLButtonElement>(null);
  if (place === null) return null;

  return (
    <div className="flex flex-col gap-2">
      <div
        role="group"
        aria-label={t('row.actions', { ref: row.ref })}
        className="flex flex-wrap gap-2"
      >
        {row.review_state === 'confirmed' ? null : (
          <Button
            size="sm"
            data-action="confirm"
            aria-label={t('action.confirmLabel', { ref: row.ref })}
            disabled={confirm.isPending}
            onClick={() =>
              confirm.mutate({ place, outcome: 'confirmed', reason: '' }, { onSuccess: onReviewed })
            }
          >
            {confirm.isPending ? t('action.pending') : t('action.confirm')}
          </Button>
        )}
        <Button
          ref={reviseButton}
          size="sm"
          tone="quiet"
          data-action="revise"
          aria-label={t('action.reviseLabel', { ref: row.ref })}
          onClick={() => setDialog('revise')}
        >
          {t('action.revise')}
        </Button>
        <Button
          ref={rejectButton}
          size="sm"
          tone="quiet"
          data-action="reject"
          aria-label={t('action.rejectLabel', { ref: row.ref })}
          onClick={() => setDialog('rejected')}
        >
          {t('action.reject')}
        </Button>
        <Button
          ref={removeButton}
          size="sm"
          tone="quiet"
          data-action="remove"
          aria-label={t('action.removeLabel', { ref: row.ref })}
          onClick={() => setDialog('removed')}
        >
          {t('action.remove')}
        </Button>
      </div>

      {confirm.isError ? (
        <Callout tone="danger">
          {errorMessage(confirm.error)} {t('retrySafe')}
        </Callout>
      ) : null}

      <ReviseDialog
        row={row}
        place={place}
        open={dialog === 'revise'}
        onOpenChange={(next) => setDialog(next ? 'revise' : null)}
        onDone={onReviewed}
        returnFocus={reviseButton}
      />
      <TakeDialog
        row={row}
        place={place}
        outcome="rejected"
        open={dialog === 'rejected'}
        onOpenChange={(next) => setDialog(next ? 'rejected' : null)}
        onDone={onReviewed}
        returnFocus={rejectButton}
      />
      <TakeDialog
        row={row}
        place={place}
        outcome="removed"
        open={dialog === 'removed'}
        onOpenChange={(next) => setDialog(next ? 'removed' : null)}
        onDone={onReviewed}
        returnFocus={removeButton}
      />
    </div>
  );
}
