import { useTranslation } from 'react-i18next';
import { Link } from 'react-router';
import { useQuery } from '@tanstack/react-query';
import { tasksTotalQueryOptions } from '@/entities/task';
import { errorMessage } from '@/shared/errors';
import { useLanguage } from '@/shared/i18n';
import { formatNumber } from '@/shared/lib';
import { EMPTY_FILTERS, filtersToListParams, type TaskFilters } from '../model/filters';
import { tasksHref } from '../model/href';

type CounterId = 'inProgress' | 'open' | 'waiting' | 'warnings';

/** Четыре отбора строки (TRK#46): независимые, задача может попасть в два сразу. */
function counterChanges(
  id: CounterId,
  scope: Pick<TaskFilters, 'project' | 'area'>,
): Partial<TaskFilters> {
  switch (id) {
    case 'inProgress':
      return { ...scope, status: ['in_progress'] };
    case 'open':
      return { ...scope, status: ['open'] };
    case 'waiting':
      return { ...scope, withWaiting: true };
    case 'warnings':
      return { ...scope, withWarnings: true };
  }
}

const COUNTERS: readonly CounterId[] = ['inProgress', 'open', 'waiting', 'warnings'];

interface TaskCountersProps {
  /** Ключ проекта. */
  project: string;
  /** Адрес области `PROJECT/key`; без него — весь проект. */
  area?: string;
}

/**
 * Строка из четырёх чисел под описанием проекта или области (TRK-619, решение
 * TRK#46): «В работе», «Открыто», «Ждут ответа», «Закрыты не целиком».
 *
 * Отбор один и питает и число, и ссылку: `filtersToListParams` даёт запрос, `tasksHref`
 * — адрес списка, поэтому число равно заголовку списка по этой ссылке. Число — только
 * `meta.total` (`tasksTotalQueryOptions`): на клиенте ничего не считается, сумм и долей
 * нет. Ноль — нулём и тоже ссылкой; `null` — ссылка без числа; отказ одного запроса
 * ставит у его счётчика прочерк и не трогает остальные.
 */
export function TaskCounters({ project, area }: TaskCountersProps) {
  const { t } = useTranslation('tasks');

  return (
    <ul
      className="flex list-none flex-wrap items-baseline gap-x-5 gap-y-1 p-0"
      aria-label={t('counters.label')}
      data-counters=""
    >
      {COUNTERS.map((id) => (
        <li key={id}>
          <Counter id={id} project={project} area={area ?? ''} />
        </li>
      ))}
    </ul>
  );
}

function Counter({ id, project, area }: { id: CounterId; project: string; area: string }) {
  const { t } = useTranslation('tasks');
  const { language } = useLanguage();

  const changes = counterChanges(id, { project, area });
  const filters: TaskFilters = { ...EMPTY_FILTERS, ...changes };
  const total = useQuery(tasksTotalQueryOptions(filtersToListParams(filters)));
  const failed = total.isError && total.data === undefined;

  let value: string | null = null;
  if (total.data !== undefined && total.data !== null) value = formatNumber(total.data, language);

  return (
    <Link
      to={tasksHref('', changes)}
      className="inline-flex items-baseline gap-1.5"
      data-counter={id}
      title={failed ? errorMessage(total.error) : undefined}
    >
      <span>{t(`counters.${id}`)}</span>
      {/* Место числа занято на четыре знака: пока оно читается, строка не прыгает. */}
      <span
        className="inline-block min-w-[3ch] font-semibold text-muted tabular-nums"
        aria-busy={total.isPending}
      >
        {failed ? (
          <>
            <span aria-hidden="true">—</span>
            <span className="sr-only">{errorMessage(total.error)}</span>
          </>
        ) : total.isPending ? (
          <span aria-hidden="true">…</span>
        ) : (
          value
        )}
      </span>
    </Link>
  );
}
