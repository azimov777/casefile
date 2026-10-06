import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router';
import { useQuery } from '@tanstack/react-query';
import { DirectionLink, directionsQueryOptions, type DirectionCard } from '@/entities/direction';
import { CreateDirection, DirectionArchiving, EditDirection } from '@/features/manage-project';
import { tasksHref } from '@/features/task-filters';
import { QueryState } from '@/shared/ui';

/** Блок-список, как атрибуты и решения рядом: строки идут до краёв поверхности. */
const LIST_BLOCK = 'flex flex-col gap-0 rounded-control border border-line bg-surface';

/** Заголовок блока-списка: поля и линия под ним. */
const BLOCK_HEAD = 'flex flex-col gap-1 border-b border-b-line px-3 pt-3 pb-2';

/** Строка направления: поля как у строки атрибута, линия между строками. */
const ROW = 'flex flex-col gap-1 border-b border-b-line px-3 py-2 last:border-b-0';

interface ProjectDirectionsProps {
  projectKey: string;
  /** Заводить, править и архивировать направления: запись открыта всем, проект не в архиве. */
  canWrite: boolean;
}

/**
 * Раздел «Направления» экрана проекта (TRK-557, TRK#16, ч. 4): части работы проекта без
 * конца — список, заведение, правка, архив и обратно.
 *
 * Список читается отдельным запросом, а не из карточки проекта: в карточке у направления
 * только адрес и название, а строке нужны описание и признак архива. Архивные бэкенд
 * прячет, пока их не попросили (`include_archived`), — так же, как архивные проекты из
 * панели; флажок «Показать архивные» просит их, данных не меняя, и потому это
 * переключатель, а не действие.
 *
 * У строки — ссылка в список задач с отбором по этому направлению: тот же адрес, каким
 * отбирает человек в самом списке, и то же условие `direction`, каким отбирает агент.
 */
export function ProjectDirections({ projectKey, canWrite }: ProjectDirectionsProps) {
  const { t } = useTranslation('direction');
  const [showArchived, setShowArchived] = useState(false);
  const list = useQuery(directionsQueryOptions(projectKey, showArchived));

  const directions = list.data?.items ?? [];

  return (
    <section className={LIST_BLOCK} aria-labelledby="project-directions">
      <div className={BLOCK_HEAD}>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-screen" id="project-directions">
            {t('section.title')}
          </h2>
          {canWrite ? <CreateDirection projectKey={projectKey} /> : null}
        </div>
        <p className="text-meta text-muted">{t('section.hint')}</p>
        <label className="inline-flex items-center gap-1.5 self-start text-meta text-muted max-fold:min-h-(--ui-tap)">
          <input
            type="checkbox"
            className="size-(--ui-mark) accent-accent"
            checked={showArchived}
            onChange={(event) => setShowArchived(event.target.checked)}
          />
          {t('section.showArchived')}
        </label>
      </div>

      {list.data === undefined ? (
        <div className="px-3 py-2">
          <QueryState query={list} loading={t('section.loading')} />
        </div>
      ) : directions.length === 0 ? (
        <p className="px-3 py-2 text-muted italic">
          {showArchived ? t('section.noneAtAll') : t('section.none')}
        </p>
      ) : (
        <ul className="flex list-none flex-col p-0" aria-label={t('section.title')}>
          {directions.map((direction) => (
            <DirectionRow
              key={direction.address}
              projectKey={projectKey}
              direction={direction}
              canWrite={canWrite}
            />
          ))}
        </ul>
      )}

      {/* Страница направлений покрывает проект целиком почти всегда; если нет — сказано
          словами, а не показаны молча первые двести. */}
      {list.data?.meta?.has_more === true ? (
        <p className="px-3 py-2 text-meta text-muted">{t('section.more')}</p>
      ) : null}
    </section>
  );
}

/**
 * Одно направление: название ссылкой на его страницу и адрес, ниже — описание, ещё
 * ниже — задачи направления и действия. Действия — своей строкой, как у атрибута: на
 * 390 px название, адрес и три кнопки в одну строку не встают.
 */
function DirectionRow({
  projectKey,
  direction,
  canWrite,
}: {
  projectKey: string;
  direction: DirectionCard;
  canWrite: boolean;
}) {
  const { t } = useTranslation('direction');
  const archived = direction.archived_at !== null;

  return (
    <li className={ROW} data-direction-row={direction.address}>
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <DirectionLink
          address={direction.address}
          title={direction.title}
          archivedAt={direction.archived_at}
          className="font-semibold"
        />
        <span className="font-mono text-meta whitespace-nowrap text-muted">
          {direction.address}
        </span>
      </div>
      {direction.description.trim() === '' ? null : (
        <p className="text-meta wrap-anywhere text-muted">{direction.description}</p>
      )}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <Link
          className="text-meta"
          to={tasksHref('', { project: projectKey, direction: direction.address })}
        >
          {t('section.tasks')}
        </Link>
        {canWrite && !archived ? <EditDirection direction={direction} /> : null}
        {canWrite ? <DirectionArchiving address={direction.address} archived={archived} /> : null}
      </div>
    </li>
  );
}
