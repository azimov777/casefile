import { useTranslation } from 'react-i18next';
import { useInfiniteQuery } from '@tanstack/react-query';
import { EntryCard, projectCaseQueryOptions } from '@/entities/entry';
import type { ProjectAttribute } from '@/entities/project';
import { AddAttribute, ChangeAttribute, RemoveAttribute } from '@/features/manage-project';
import { Button, QueryState, RelativeTime } from '@/shared/ui';

/** Блок-список, как у дела рядом: строки атрибутов идут до краёв поверхности. */
const LIST_BLOCK = 'flex flex-col gap-0 rounded-control border border-line bg-surface';

/** Заголовок блока-списка: поля и линия под ним. */
const BLOCK_HEAD = 'flex flex-col gap-1 border-b border-b-line px-3 pt-3 pb-2';

interface ProjectAttributesProps {
  projectKey: string;
  attributes: ProjectAttribute[];
  /** Ставить, менять и снимать атрибуты: любой набор ключа (`useProjectRights`). */
  canWrite: boolean;
  /** Имя атрибута из адреса (`?attribute=`), чья история открыта; `null` — ничья. */
  open: string | null;
  onOpenChange: (name: string | null) => void;
}

/**
 * Атрибуты проекта: имя и нынешнее значение, история — по клику на имя.
 *
 * Порядок — тот, что отдал бэкенд (по имени без учёта регистра). Значение — простой
 * текст, который трекер не толкует (`AttributeRead.value`): он показывается как есть,
 * с переносами строк, а не markdown-ом — ссылкой в нём станет только то, что напишут
 * ссылкой в деле.
 */
export function ProjectAttributes({
  projectKey,
  attributes,
  canWrite,
  open,
  onOpenChange,
}: ProjectAttributesProps) {
  const { t } = useTranslation('project');

  return (
    <section className={LIST_BLOCK} aria-labelledby="project-attributes">
      <div className={BLOCK_HEAD}>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-screen" id="project-attributes">
            {t('attributes')}
          </h2>
          {canWrite ? <AddAttribute projectKey={projectKey} /> : null}
        </div>
        {attributes.length > 0 ? (
          <p className="text-meta text-muted">{t('attributesHint')}</p>
        ) : null}
      </div>

      {attributes.length === 0 ? (
        <p className="px-3 py-2 text-muted italic">{t('noAttributes')}</p>
      ) : (
        <ul className="flex list-none flex-col p-0">
          {attributes.map((attribute) => {
            // Имя уникально без учёта регистра: адрес, набранный руками в другом
            // регистре, открывает тот же атрибут.
            const expanded = open !== null && open.toLowerCase() === attribute.name.toLowerCase();
            const historyId = `attribute-history-${attribute.name}`;
            return (
              <li
                key={attribute.name}
                className="flex flex-col gap-1 border-b border-b-line px-3 py-2 last:border-b-0"
                data-attribute={attribute.name}
              >
                <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                  {/*
                   * Имя — кнопка: раскрытие истории это действие, и с клавиатуры оно
                   * тоже нужно. Вид тот же, что у заголовка записи в описи
                   * (`EntryIndex`): треугольник псевдоэлементом, фон и рамка названы
                   * явно (`docs/notes/ui.md`, «Кнопка без объявленного фона»).
                   */}
                  <button
                    type="button"
                    className="cursor-pointer border-none border-current bg-transparent p-0 text-left font-mono font-semibold text-text wrap-anywhere before:text-muted before:content-['▸_'] max-fold:min-h-(--ui-tap) hover:underline aria-expanded:before:content-['▾_']"
                    aria-expanded={expanded}
                    aria-controls={expanded ? historyId : undefined}
                    onClick={() => onOpenChange(expanded ? null : attribute.name)}
                  >
                    {attribute.name}
                  </button>
                  <span className="text-meta text-muted">
                    <RelativeTime value={attribute.updated_at} />
                  </span>
                </div>
                <p className="whitespace-pre-wrap wrap-anywhere">{attribute.value}</p>
                {/* Действия — под значением, а не в строке имени: на 390 px имя, время и
                    две кнопки в одну строку не встают, а перенос посреди них читается
                    хуже, чем своя строка. */}
                {canWrite ? (
                  <div className="flex flex-wrap gap-2">
                    <ChangeAttribute projectKey={projectKey} attribute={attribute} />
                    <RemoveAttribute projectKey={projectKey} attribute={attribute} />
                  </div>
                ) : null}
                {expanded ? (
                  <AttributeHistory projectKey={projectKey} name={attribute.name} id={historyId} />
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

/**
 * История одного атрибута: записи дела проекта о нём, по порядку номеров — заведение,
 * изменения с прежним и новым значением и снятие, каждая с причиной.
 *
 * Отбор — серверный параметр `attribute` (TRK-166): бэкенд сам сужает выдачу до трёх
 * типов записи об атрибутах и до этого имени, без учёта регистра, страницами по курсору.
 * У проекта с записями многих атрибутов история одного открывается без страниц чужих
 * записей между нужными — раньше экран запрашивал все три типа и отбирал по имени сам.
 * Записи показаны теми же карточками, что в ленте дела задачи (`EntryCard`): «было /
 * стало» и причина под ним.
 */
function AttributeHistory({
  projectKey,
  name,
  id,
}: {
  projectKey: string;
  name: string;
  id: string;
}) {
  const feed = useInfiniteQuery(projectCaseQueryOptions(projectKey, { attribute: name }));
  const { t } = useTranslation('project');

  const history = feed.data?.pages.flatMap((page) => page.items) ?? [];

  return (
    <div
      id={id}
      role="region"
      aria-label={t('history', { name })}
      className="flex flex-col gap-2 pt-1"
    >
      {feed.data === undefined ? (
        <QueryState query={feed} loading={t('historyLoading')} />
      ) : history.length === 0 && !feed.hasNextPage ? (
        <p className="text-muted italic">{t('historyEmpty')}</p>
      ) : (
        /* Нить времени — та же, что у ленты дела: точка рода каждой записи стоит на ней. */
        <div className="relative flex flex-col gap-2 pl-8 before:absolute before:top-2 before:bottom-2 before:left-2.5 before:w-px before:bg-line">
          {history.map((entry) => (
            <EntryCard key={entry.no} entry={entry} />
          ))}
        </div>
      )}
      {feed.hasNextPage ? (
        <div>
          <Button
            tone="quiet"
            size="sm"
            onClick={() => void feed.fetchNextPage()}
            disabled={feed.isFetchingNextPage}
          >
            {feed.isFetchingNextPage ? t('loadingMore') : t('more')}
          </Button>
        </div>
      ) : null}
    </div>
  );
}
