import { useId, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { CircleHelp, Flag, Lock } from 'lucide-react';
import { PriorityMark, StatusMark, TASK_PRIORITIES, TASK_STATUSES } from '@/entities/task';
import { cn } from '@/shared/lib';
import { FilterGroup, ToggleGroup, ToggleGroupItem } from '@/shared/ui';
import { type TaskFilters } from '../model/filters';
import { FIELD, FIELD_PENDING } from './field';
import { PendingMark } from './query-problem-hint';

/** Признаки задачи, которыми отбирают: значение группы → поле отбора. */
const FLAGS = ['blocked', 'withQuestions', 'withRemarks'] as const;
type FlagName = (typeof FLAGS)[number];

/**
 * Знак признака — тот же, каким признак стоит в строке списка (`TaskFeatureMarks`):
 * человек отбирает по тому, что видит в колонке «Признаки», и узнаёт его здесь по знаку.
 */
const FLAG_ICON = {
  blocked: Lock,
  withQuestions: CircleHelp,
  withRemarks: Flag,
} satisfies Record<FlagName, typeof Lock>;

interface FilterMenuProps {
  filters: TaskFilters;
  board: boolean;
  /** Исполнитель в поле — черновик: применяется по Enter, как поиск в строке. */
  assignee: string;
  pending: boolean;
  onAssignee: (value: string) => void;
  onApply: (changes: Partial<TaskFilters>) => void;
}

/**
 * Панель «Фильтр»: все условия простого отбора, каждое — одним нажатием.
 *
 * Переключатели применяются сразу и панель не закрывают: человек, отбирающий по двум
 * признакам, не открывает её дважды. Исполнитель — свободная строка (агенты бывают
 * временными и в реестре не значатся), поэтому поле, а не список.
 */
export function FilterMenu({
  filters,
  board,
  assignee,
  pending,
  onAssignee,
  onApply,
}: FilterMenuProps) {
  const assigneeId = useId();
  const pendingId = useId();
  const { t } = useTranslation('tasks');
  const flags = FLAGS.filter((flag) => filters[flag]);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onApply({});
  }

  return (
    <div className="flex flex-col gap-3">
      {/* На доске статус — это столбец: отбирать по нему ещё и здесь значило бы врать. */}
      {board ? null : (
        <FilterGroup label={t('filters.statusLegend')}>
          {(labelId) => (
            <ToggleGroup
              aria-labelledby={labelId}
              value={filters.status}
              onValueChange={(status) => onApply({ status: status as TaskFilters['status'] })}
            >
              {TASK_STATUSES.map((status) => (
                /* Статус тем же знаком, что в строке списка и на доске. */
                <ToggleGroupItem key={status} value={status}>
                  <StatusMark status={status} />
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
          )}
        </FilterGroup>
      )}

      <FilterGroup label={t('filters.priorityLegend')}>
        {(labelId) => (
          <ToggleGroup
            aria-labelledby={labelId}
            value={filters.priority}
            onValueChange={(priority) => onApply({ priority: priority as TaskFilters['priority'] })}
          >
            {TASK_PRIORITIES.map((priority) => (
              <ToggleGroupItem key={priority} value={priority}>
                <PriorityMark priority={priority} />
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
        )}
      </FilterGroup>

      <FilterGroup label={t('filters.flagsLegend')}>
        {(labelId) => (
          <ToggleGroup
            aria-labelledby={labelId}
            value={flags}
            onValueChange={(value) =>
              onApply(
                Object.fromEntries(
                  FLAGS.map((flag) => [flag, (value as FlagName[]).includes(flag)]),
                ) as Pick<TaskFilters, FlagName>,
              )
            }
          >
            {FLAGS.map((flag) => {
              const Icon = FLAG_ICON[flag];
              return (
                <ToggleGroupItem key={flag} value={flag}>
                  <Icon className="size-(--ui-mark) shrink-0" aria-hidden="true" />
                  {t(`filters.${flag}`)}
                </ToggleGroupItem>
              );
            })}
          </ToggleGroup>
        )}
      </FilterGroup>

      <form className="flex flex-col gap-1.5" onSubmit={submit}>
        <label className="text-label text-muted" htmlFor={assigneeId}>
          {t('filters.assignee')}
        </label>
        <div className="relative flex items-center">
          <input
            id={assigneeId}
            className={cn(FIELD, pending ? FIELD_PENDING : 'border-line-strong')}
            value={assignee}
            onChange={(event) => onAssignee(event.target.value)}
            placeholder={t('filters.assigneePlaceholder')}
            aria-describedby={pending ? pendingId : undefined}
            autoComplete="off"
            spellCheck={false}
          />
          {pending ? <PendingMark id={pendingId} /> : null}
        </div>
      </form>
    </div>
  );
}
