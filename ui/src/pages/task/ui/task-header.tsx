import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import {
  PriorityMark,
  StatusMark,
  TaskFeatureMarks,
  type TaskDetails,
  type TaskFeatures,
} from '@/entities/task';
import { RelativeTime } from '@/shared/ui';

interface TaskHeaderProps {
  task: TaskDetails;
  features: TaskFeatures;
}

/** Отсутствующее значение: курсив вместо прочерка — его читают, а не сканируют. */
const EMPTY = 'text-muted italic';

/** Шапка карточки: где задача стоит и чья она. */
export function TaskHeader({ task, features }: TaskHeaderProps) {
  const { t } = useTranslation('task');

  return (
    <header className="flex flex-col gap-2">
      <p className="text-meta">
        <Link to={`/tasks?queue=${task.queue.key}`}>
          {task.queue.key} — {task.queue.title}
        </Link>
      </p>

      {/* Междустрочие названия шире, чем у заголовков вообще (1.25 в сбросе): название
          задачи бывает в три строки, и на кегле 19 px они слипались. */}
      <h1 className="text-title leading-[1.3]">
        <span className="font-mono text-muted">{task.key}</span> {task.title}
      </h1>

      {/*
       * Разные вещи перестали быть одинаковыми плашками (решение Д7): статус — форма
       * со значением, приоритет — высота столбиков, исполнитель — имя с аватаром. Род
       * значения при этом никуда не делся: он ушёл в доступное имя знака.
       */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <StatusMark status={task.status} />
        <PriorityMark priority={task.priority} />

        {/*
         * Исполнитель — не плашка, а имя с аватаром: плашка уравнивала его со статусом,
         * хотя это единственная в шапке строка про человека. Род значения остаётся
         * в доступном имени.
         */}
        <span className="inline-flex items-center gap-1.5 text-meta text-muted">
          <span className="sr-only">{t('header.assignee')} </span>
          {task.assignee === null ? (
            <span className={EMPTY}>{t('header.unassigned')}</span>
          ) : (
            <>
              {/* Аватар из двух букв: круг с границей, а не заливкой цвета участника —
                  цветов у нас шесть и все они называют положение дел, а не сущность. */}
              <span
                className="grid size-5 place-items-center rounded-pill border border-line-strong bg-sunken text-label font-semibold"
                aria-hidden="true"
              >
                {task.assignee.slice(0, 2)}
              </span>
              <span className="font-mono text-mark">{task.assignee}</span>
            </>
          )}
        </span>

        {/* Признаки в той же строке, что и плашки: две отдельные строки одинаковых
            плашек занимали место главного, ничего не добавляя к различимости. */}
        <TaskFeatureMarks features={features} />
      </div>

      <dl className="flex flex-wrap gap-x-6 gap-y-2 text-meta">
        <div className="flex items-baseline gap-2">
          <dt className="text-muted">{t('header.updated')}</dt>
          <dd>
            <RelativeTime value={task.updated_at} />
          </dd>
        </div>
        <div className="flex items-baseline gap-2">
          <dt className="text-muted">{t('header.created')}</dt>
          <dd>
            <RelativeTime value={task.created_at} />
          </dd>
        </div>
      </dl>
    </header>
  );
}
