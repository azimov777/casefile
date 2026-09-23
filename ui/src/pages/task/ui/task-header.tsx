import { Fragment } from 'react';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import {
  PriorityMark,
  StatusMark,
  TaskFeatureMarks,
  hasFeatureBadges,
  type TaskDetails,
  type TaskFeatures,
  type TaskLink,
} from '@/entities/task';
import { RelativeTime } from '@/shared/ui';

interface TaskHeaderProps {
  task: TaskDetails;
  features: TaskFeatures;
  /** Связи задачи из пакета: из них берутся родители для строки «где». */
  links: TaskLink[];
}

/** Отсутствующее значение: курсив вместо прочерка — его читают, а не сканируют. */
const EMPTY = 'text-muted italic';

/** Ячейка полосы свойств: подпись над значением. */
const CELL = 'flex flex-col gap-1';

/** Подпись значения: мельче и тише самого значения, чтобы читалось значение. */
const LABEL = 'text-label text-muted';

/**
 * Шапка карточки — группы, которые читаются с первого взгляда (UI-143, вариант B,
 * выбранный владельцем в UI-143#10):
 *
 * 1. «Где» и «что» — очередь, родители и название — одна группа с шагом 4 px: очередь
 *    и родитель читаются надписью над названием, а не отдельной строкой.
 * 2. Состояние и время — полоса свойств между двумя линиями, в 12 px под названием.
 *    Каждое значение подписано (`dt`), поэтому статус принадлежит задаче по подписи,
 *    а не по близости к соседней строке. Время стоит в правом конце полосы: это тоже
 *    свойство задачи, но другого рода, и отделено оно местом, а не цветом.
 *
 * Раньше все строки стояли на одном шаге 8 px, и строка статуса была одинаково близка
 * и к названию, и к датам — владелец не мог сказать, к чему она относится. Строку
 * действий от шапки отделяет 24 px (`mt-2` поверх шага страницы 16): больше любого
 * зазора внутри шапки.
 */
export function TaskHeader({ task, features, links }: TaskHeaderProps) {
  const { t } = useTranslation('task');
  const { t: brick } = useTranslation('ui');

  // `child` назван от лица этой задачи: «я ребёнок той». Порядок — порядок связей.
  const parents = links.filter((link) => link.kind === 'child');

  return (
    <header className="mt-2 flex flex-col gap-3">
      <div className="flex flex-col gap-1">
        <p className="flex flex-wrap items-baseline gap-x-2 text-meta">
          <Link to={`/tasks?queue=${task.queue.key}`}>
            {task.queue.key} — {task.queue.title}
          </Link>
          {parents.map((parent) => (
            <Fragment key={parent.other.key}>
              <span className="text-faint" aria-hidden="true">
                /
              </span>
              <Link to={`/tasks/${parent.other.key}`}>
                <span className="sr-only">{brick('task.parents.label')} </span>
                <span className="font-mono">{parent.other.key}</span> {parent.other.title}
              </Link>
            </Fragment>
          ))}
        </p>

        {/* Междустрочие названия шире, чем у заголовков вообще (1.25 в сбросе): название
            задачи бывает в три строки, и на кегле 19 px они слипались. */}
        <h1 className="text-title leading-[1.3]">
          <span className="font-mono text-muted">{task.key}</span> {task.title}
        </h1>
      </div>

      {/*
       * Разные вещи — разной формой (решение Д7): статус — форма со значением, приоритет —
       * высота столбиков, исполнитель — имя с аватаром. Род значения назван подписью
       * `dt`, поэтому знакам своё скрытое «статус»/«приоритет» не нужно (`labelled`).
       *
       * Линия названа стороной (`border-y-line`): `border-line` красил бы все четыре.
       */}
      <dl className="flex flex-wrap items-start gap-x-6 gap-y-3 border-y border-y-line py-2 text-meta">
        <div className={CELL}>
          <dt className={LABEL}>{t('header.status')}</dt>
          <dd>
            <StatusMark status={task.status} labelled={false} />
          </dd>
        </div>
        <div className={CELL}>
          <dt className={LABEL}>{t('header.priority')}</dt>
          <dd>
            <PriorityMark priority={task.priority} labelled={false} />
          </dd>
        </div>
        <div className={CELL}>
          <dt className={LABEL}>{t('header.assignee')}</dt>
          <dd className="inline-flex items-center gap-1.5 text-muted">
            {task.assignee === null ? (
              <span className={EMPTY}>{t('header.unassigned')}</span>
            ) : (
              <>
                {/* Аватар из двух букв: круг с границей, а не заливкой цвета участника —
                    цвета у нас называют положение дел, а не сущность. */}
                <span
                  className="grid size-5 place-items-center rounded-pill border border-line-strong bg-sunken text-label font-semibold"
                  aria-hidden="true"
                >
                  {task.assignee.slice(0, 2)}
                </span>
                <span className="font-mono text-mark">{task.assignee}</span>
              </>
            )}
          </dd>
        </div>

        {/* Ячейки признаков нет, когда их нет: пустая подпись читалась бы как «данные не
            пришли». Решение то же, что у строки и карточки доски (`hasFeatureBadges`). */}
        {hasFeatureBadges(features) ? (
          <div className={CELL}>
            <dt className={LABEL}>{t('header.flags')}</dt>
            <dd className="flex flex-wrap gap-2">
              <TaskFeatureMarks features={features} />
            </dd>
          </div>
        ) : null}

        {/*
         * Время — в правом конце полосы (`fold:ml-auto` на первой из двух ячеек): отделено
         * местом от состояния. На телефоне полоса переносится, и время встаёт своей
         * строкой у левого края, как остальные ячейки.
         */}
        <div className={`${CELL} fold:ml-auto`}>
          <dt className={LABEL}>{t('header.updated')}</dt>
          <dd>
            <RelativeTime value={task.updated_at} />
          </dd>
        </div>
        <div className={CELL}>
          <dt className={LABEL}>{t('header.created')}</dt>
          <dd>
            <RelativeTime value={task.created_at} />
          </dd>
        </div>
      </dl>
    </header>
  );
}
