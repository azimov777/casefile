import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { AreaLink } from '@/entities/area';
import { DecisionStatusMark } from '@/entities/entry';
import { decisionHref } from '@/entities/project';
import {
  PriorityMark,
  StatusMark,
  TaskFeatureMarks,
  hasFeatureBadges,
  type CitedDecision,
  type TaskDetails,
  type LinkedTask,
  type TaskFeatures,
} from '@/entities/task';
import { ChangeTaskArea } from '@/features/change-task-area';
import { TaskNotBefore } from '@/features/change-task-not-before';
import { RelativeTime } from '@/shared/ui';

interface TaskHeaderProps {
  task: TaskDetails;
  features: TaskFeatures;
  /** Родитель задачи из пакета (`parent`, TRK-135) для строки «где»; `null` — верхний уровень. */
  parent: LinkedTask | null;
  /** Решения проекта, на которые опирается задача (`decisions` пакета, TRK-554). */
  decisions: CitedDecision[];
  /**
   * Может ли человек сменить область (TRK-557): сеанс известен, задача не закрыта и
   * её проект не в архиве. Иначе ячейка только читается — кнопки нет, а не «есть и падает».
   */
  canChangeArea: boolean;
  /** Может ли человек поставить, изменить и снять момент «можно взять с …» (TRK-593): те же условия. */
  canChangeNotBefore: boolean;
}

/** Отсутствующее значение: курсив вместо прочерка — его читают, а не сканируют. */
const EMPTY = 'text-muted italic';

/** Ячейка полосы свойств: подпись над значением. */
const CELL = 'flex flex-col gap-1';

/** Подпись значения: мельче и тише самого значения, чтобы читалось значение. */
const LABEL = 'text-label text-muted';

/** Ссылка на решение проекта `TRK#15`: ключ контракта моноширинным и целиком. */
const DECISION_REF = 'font-mono text-mark whitespace-nowrap';

/**
 * Шапка карточки — группы, которые читаются с первого взгляда (UI-143, вариант B,
 * выбранный владельцем в UI-143#10):
 *
 * 1. «Где» и «что» — проект, область, родители и название — одна группа с шагом
 *    4 px: проект, область и родитель читаются надписью над названием, а не
 *    отдельной строкой.
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
export function TaskHeader({
  task,
  features,
  parent,
  decisions,
  canChangeArea,
  canChangeNotBefore,
}: TaskHeaderProps) {
  const { t } = useTranslation('task');
  const { t: brick } = useTranslation('ui');
  const inFlags = { ...features, deferred: false };

  return (
    <header className="mt-2 flex flex-col gap-3">
      <div className="flex flex-col gap-1">
        <p className="flex flex-wrap items-baseline gap-x-2 text-meta">
          <Link to={`/tasks?project=${task.project.key}`}>
            {task.project.key} — {task.project.title}
          </Link>
          {/*
           * Область — рядом с проектом (TRK-557, TRK#16, ч. 4): тоже ответ на вопрос
           * «где», но другой оси, чем родитель, — «про что эта работа в проекте». Поэтому
           * отделена точкой, а не косой чертой: шагом вниз по пути она не является.
           */}
          {task.area === null ? null : (
            <>
              <span className="text-faint" aria-hidden="true">
                ·
              </span>
              <AreaLink
                address={task.area.address}
                title={task.area.title}
                archivedAt={task.area.archived_at}
              />
            </>
          )}
          {/*
           * Косая черта — шаг вниз по пути «проект / родитель / эта задача». Родитель у
           * задачи один: с TRK-135 это правило бэкенда (второй — `409 task_has_parent`),
           * и пакет отдаёт его полем `parent`, а не видом `child` в `links`.
           */}
          {parent === null ? null : (
            <>
              <span className="text-faint" aria-hidden="true">
                /
              </span>
              <Link to={`/tasks/${parent.key}`}>
                <span className="sr-only">{brick('task.parents.label')} </span>
                <span className="font-mono whitespace-nowrap">{parent.key}</span> {parent.title}
              </Link>
            </>
          )}
        </p>

        {/* Междустрочие названия шире, чем у заголовков вообще (1.25 в сбросе): название
            задачи бывает в три строки, и на кегле 19 px они слипались. */}
        <h1 className="text-title leading-[1.3]">
          {/* `whitespace-nowrap` держит ключ целым, если заголовок переносится сразу
              после него (UI-151). */}
          <span className="font-mono text-muted whitespace-nowrap">{task.key}</span> {task.title}
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
        {/*
         * Область — сразу за приоритетом: поле обвязки, которое человек правит там же,
         * где видит (TRK#16, ч. 4). Значение — адресом моноширинным: название уже стоит
         * ссылкой над заголовком, а здесь — то, что уходит в поле задачи и в отбор.
         */}
        <div className={CELL}>
          <dt className={LABEL}>{t('header.area')}</dt>
          <dd className="flex flex-wrap items-center gap-x-2 gap-y-1">
            {task.area === null ? (
              <span className={EMPTY}>{t('header.noArea')}</span>
            ) : (
              <span className="font-mono text-mark text-muted">{task.area.address}</span>
            )}
            {canChangeArea ? (
              <ChangeTaskArea
                taskKey={task.key}
                projectKey={task.project.key}
                current={task.area}
              />
            ) : null}
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

        {/*
         * Прежние ключи (TRK-173, TRK/ui-screens#8): видны только у
         * перенесённой задачи, ячейки нет вовсе, когда переносов не было — как у
         * признаков ниже. Каждый ключ — ссылка на ту же задачу (`named_by` на
         * бэкенде): адрес откроет её и сам заменится на текущий ключ.
         */}
        {task.previous_keys.length > 0 ? (
          <div className={CELL}>
            <dt className={LABEL}>{t('header.previousKeys')}</dt>
            <dd className="flex flex-wrap gap-x-2 gap-y-1 font-mono text-mark text-muted">
              {task.previous_keys.map((previousKey) => (
                <Link key={previousKey} to={`/tasks/${previousKey}`} className="whitespace-nowrap">
                  {previousKey}
                </Link>
              ))}
            </dd>
          </div>
        ) : null}

        {/*
         * Момент «можно взять с …» (TRK-593, TRK#47, п. 6): ячейка есть, когда он задан или
         * его можно поставить. Значок отложенной задачи стоит в ней самой, поэтому из ячейки
         * признаков он убран: дважды один знак в одной полосе — шум.
         */}
        {task.not_before !== null || canChangeNotBefore ? (
          <div className={CELL}>
            <dt className={LABEL}>{t('header.notBefore')}</dt>
            <dd>
              <TaskNotBefore
                taskKey={task.key}
                notBefore={task.not_before}
                deferred={features.deferred}
                canChange={canChangeNotBefore}
              />
            </dd>
          </div>
        ) : null}

        {/* Ячейки признаков нет, когда их нет: пустая подпись читалась бы как «данные не
            пришли». Решение то же, что у строки и карточки доски (`hasFeatureBadges`). */}
        {hasFeatureBadges(inFlags) ? (
          <div className={CELL}>
            <dt className={LABEL}>{t('header.flags')}</dt>
            <dd className="flex flex-wrap gap-2">
              <TaskFeatureMarks features={inFlags} pressable />
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

        {/*
         * Решения проекта, на которые опирается задача (TRK-554): своей строкой во всю
         * ширину полосы — у решения название фразой, и в ячейку рядом со статусом оно не
         * встаёт. Строки нет вовсе, когда задача ни на что не ссылается, как у прежних
         * ключей. Статус посчитан бэкендом при чтении: заменённое решение зачёркнуто, и
         * рядом то, что его заменило, со своим статусом.
         */}
        {decisions.length > 0 ? (
          <div className={`${CELL} basis-full`}>
            <dt className={LABEL}>{t('header.decisions')}</dt>
            <dd>
              <ul className="flex list-none flex-col gap-1 p-0">
                {decisions.map((decision) => (
                  <li
                    key={decision.ref}
                    className="flex flex-wrap items-baseline gap-x-2 gap-y-1"
                    data-decision={decision.ref}
                    data-status={decision.status}
                  >
                    <Link to={decisionHref(decision.ref)} className={DECISION_REF}>
                      {decision.ref}
                    </Link>
                    <span
                      className={
                        decision.status === 'in_force'
                          ? 'wrap-anywhere'
                          : 'text-muted line-through wrap-anywhere'
                      }
                    >
                      {decision.title}
                    </span>
                    <DecisionStatusMark status={decision.status} />
                    {decision.superseded_by == null ? null : (
                      <span className="inline-flex flex-wrap items-baseline gap-x-2 gap-y-1">
                        <span aria-hidden="true" className="text-faint">
                          →
                        </span>
                        <span className="sr-only">{t('header.supersededBy')}</span>
                        <Link
                          to={decisionHref(decision.superseded_by.ref)}
                          className={DECISION_REF}
                        >
                          {decision.superseded_by.ref}
                        </Link>
                        <span className="wrap-anywhere">{decision.superseded_by.title}</span>
                        <DecisionStatusMark status={decision.superseded_by.status} />
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            </dd>
          </div>
        ) : null}
      </dl>
    </header>
  );
}
