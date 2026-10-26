import { useTranslation } from 'react-i18next';
import { decisionTasksQuery } from '@/entities/project';
import { DecisionsReview } from '@/features/decisions/review';
import { tasksHref } from '@/features/task-filters';

/** Блок-список, как атрибуты рядом: строки решений идут до краёв поверхности. */
const LIST_BLOCK = 'flex flex-col gap-0 rounded-control border border-line bg-surface';

/** Заголовок блока-списка: поля и линия под ним. */
const BLOCK_HEAD = 'flex flex-col gap-1 border-b border-b-line px-3 pt-3 pb-2';

/** Адрес списка задач, стоящих на решении: закрытые в нём важнее открытых, архив показан. */
function decisionTasksHref(ref: string): string {
  return tasksHref('', { query: decisionTasksQuery(ref), showArchive: true });
}

/**
 * Решения проекта и всех его областей (TRK-554, TRK-758): заголовок блока, а под ним список
 * с отбором «Действующие» / «Не подтверждены» / «Показать снятые» и проверкой каждого
 * решения человеком — подтвердить, исправить, отклонить, удалить. Сам список, метки и
 * действия — `features/decisions/review`: его же показывает страница области и Входящая.
 *
 * Действует ли решение и проверено ли оно, говорит бэкенд (TRK#90); здесь только блок и
 * подписи. Архивный проект только читается: действий проверки на нём нет вовсе.
 */
export function ProjectDecisions({
  projectKey,
  canReview,
}: {
  projectKey: string;
  canReview: boolean;
}) {
  const { t } = useTranslation('project');

  return (
    <section className={LIST_BLOCK} aria-labelledby="project-decisions">
      <div className={BLOCK_HEAD}>
        <h2 className="text-screen" id="project-decisions">
          {t('decisions.title')}
        </h2>
        <p className="text-meta text-muted">{t('decisions.hint')}</p>
      </div>
      <DecisionsReview project={projectKey} canReview={canReview} tasksHref={decisionTasksHref} />
    </section>
  );
}
