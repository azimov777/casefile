import { TriangleAlert } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import {
  AuthorName,
  isIncompleteOutcome,
  type EntryHeading,
  type IncompleteOutcome,
} from '@/entities/entry';
import { errorMessage } from '@/shared/errors';
import { useOnceKey } from '@/shared/lib';
import { Badge, Button, Markdown } from '@/shared/ui';
import { useAcceptWarning } from '../model/use-accept-warning';

interface WarningPanelProps {
  taskKey: string;
  /** Строка описи `warning`: номера проверок по исходам лежат в её фактах. */
  warning: EntryHeading;
  /** Проверки задачи: человек решает по их тексту, а в предупреждении только номера. */
  checks: string[];
  /** Можно ли реагировать: у задачи архивного проекта нельзя ничего (`project_archived`). */
  canAct: boolean;
  /**
   * «Вернуть на доработку» — это замечание (TRK#117): форму раскрывает
   * карточка, где она и живёт. Своей формы у панели нет.
   */
  onReturn: () => void;
}

/** Пары «номер проверки — исход» из фактов предупреждения, по возрастанию номера. */
function incompleteChecks(warning: EntryHeading): { no: number; outcome: IncompleteOutcome }[] {
  if (warning.facts.type !== 'warning') return [];
  const pairs = [
    ...(warning.facts.partial ?? []).map((no) => ({ no, outcome: 'partial' as const })),
    ...(warning.facts.unverifiable ?? []).map((no) => ({ no, outcome: 'unverifiable' as const })),
  ];
  return pairs
    .filter((pair) => isIncompleteOutcome(pair.outcome))
    .sort((left, right) => left.no - right.no);
}

/**
 * Плашка открытого предупреждения на карточке задачи (TRK-561).
 *
 * Стоит первой в левой колонке: это единственное на карточке, что ждёт хода именно от
 * человека, кроме вопросов, — и пока он не принял или не вернул задачу, она не уходит в
 * архив. Реакций две, и обе — записи дела: «Принять» подшивает `acceptance`,
 * «Вернуть на доработку» раскрывает форму замечания.
 */
export function WarningPanel({ taskKey, warning, checks, canAct, onReturn }: WarningPanelProps) {
  const { t } = useTranslation('ui');
  const accept = useAcceptWarning();
  const once = useOnceKey<string>();

  return (
    <section
      aria-labelledby="warning"
      className="flex flex-col gap-3 rounded-control border border-attention-line bg-attention-soft p-3"
    >
      <h2 id="warning" className="flex items-center gap-2 text-screen">
        <TriangleAlert className="size-(--ui-mark) shrink-0 text-attention" aria-hidden="true" />
        {t('warning.title')}
      </h2>
      <p>{t('warning.text')}</p>
      <ul className="flex list-none flex-col gap-2 p-0">
        {incompleteChecks(warning).map(({ no, outcome }) => {
          const check = checks[no - 1];
          return (
            <li key={no} className="flex flex-col gap-1">
              <p className="flex flex-wrap items-center gap-2 text-meta text-muted">
                <span>{t('entry.headline.check', { no })}</span>
                <Badge tone="attention">{t(`entry.verdictOutcome.${outcome}`)}</Badge>
              </p>
              {check === undefined ? null : (
                <div className="border-l-2 border-line-strong pl-3">
                  <Markdown>{check}</Markdown>
                </div>
              )}
            </li>
          );
        })}
      </ul>
      <p className="flex flex-wrap items-baseline gap-2 text-meta text-muted">
        <span>{t('warning.closedBy')}</span>
        <AuthorName author={warning.author} />
      </p>
      {canAct ? (
        <div className="flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            disabled={accept.isPending}
            onClick={() => {
              accept.mutate(
                {
                  taskKey,
                  title: t('warning.acceptTitle'),
                  idempotencyKey: once.keyFor(`${taskKey}#${warning.no}`),
                },
                { onSuccess: () => once.forget() },
              );
            }}
          >
            {accept.isPending ? t('warning.accepting') : t('warning.accept')}
          </Button>
          <Button size="sm" tone="quiet" onClick={onReturn}>
            {t('warning.return')}
          </Button>
        </div>
      ) : null}
      {accept.isError ? (
        <p role="alert" className="text-danger">
          {errorMessage(accept.error)}
        </p>
      ) : null}
    </section>
  );
}
