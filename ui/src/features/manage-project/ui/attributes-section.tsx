import { useTranslation } from 'react-i18next';
import { useInfiniteQuery } from '@tanstack/react-query';
import { EntryCard, holderCaseQueryOptions } from '@/entities/entry';
import type { ProjectAttribute } from '@/entities/project';
import { Button, QueryState, RelativeTime } from '@/shared/ui';
import type { Holder } from '../api/projects';
import { AddAttribute, ChangeAttribute, RemoveAttribute } from './attribute-dialogs';

/** Блок-список, как у дела рядом: строки атрибутов идут до краёв поверхности. */
const LIST_BLOCK = 'flex flex-col gap-0 rounded-control border border-line bg-surface';

/** Заголовок блока-списка: поля и линия под ним. */
const BLOCK_HEAD = 'flex flex-col gap-1 border-b border-b-line px-3 pt-3 pb-2';

interface AttributesSectionProps {
  /** Чьи атрибуты: проекта или его области (TRK-557) — правила у них одни. */
  holder: Holder;
  attributes: ProjectAttribute[];
  /** Ставить, менять и снимать атрибуты: запись открыта всем (`useProjectRights`). */
  canWrite: boolean;
  /** Имя атрибута из адреса (`?attribute=`), чья история открыта; `null` — ничья. */
  open: string | null;
  onOpenChange: (name: string | null) => void;
}

/**
 * Атрибуты проекта или области: имя и нынешнее значение, история — по клику на имя.
 *
 * Раздел живёт в действиях, а не на экране: его рисуют два экрана — проект и
 * область (TRK-557), — а экраны друг друга не импортируют. Здесь же стоят его
 * действия: «Добавить» над списком, «Изменить» и «Снять» — в открытой истории атрибута.
 *
 * Порядок — тот, что отдал бэкенд (по имени без учёта регистра). Значение — простой
 * текст, который трекер не толкует (`AttributeRead.value`): он показывается как есть,
 * с переносами строк, а не markdown-ом — ссылкой в нём станет только то, что напишут
 * ссылкой в деле.
 */
export function AttributesSection({
  holder,
  attributes,
  canWrite,
  open,
  onOpenChange,
}: AttributesSectionProps) {
  const { t } = useTranslation('project');
  const { t: tArea } = useTranslation('area');
  const headingId = `${holder.kind}-attributes`;

  return (
    <section className={LIST_BLOCK} aria-labelledby={headingId}>
      <div className={BLOCK_HEAD}>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-screen" id={headingId}>
            {t('attributes')}
          </h2>
          {canWrite ? <AddAttribute holder={holder} /> : null}
        </div>
        {attributes.length > 0 ? (
          <p className="text-meta text-muted">{t('attributesHint')}</p>
        ) : null}
      </div>

      {attributes.length === 0 ? (
        <p className="px-3 py-2 text-muted italic">
          {holder.kind === 'area' ? tArea('attributes.none') : t('noAttributes')}
        </p>
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
                {/* Строка-справка: имя и значение рядом (на 390 px имя над значением),
                    время последнего изменения — под значением. */}
                <div className="grid grid-cols-1 gap-x-4 gap-y-1 min-[900px]:grid-cols-[12rem_1fr]">
                  {/*
                   * Имя — кнопка: раскрытие истории это действие, и с клавиатуры оно
                   * тоже нужно. Вид тот же, что у заголовка записи в описи
                   * (`EntryIndex`): треугольник псевдоэлементом, фон и рамка названы
                   * явно (`docs/notes/ui.md`, «Кнопка без объявленного фона»).
                   */}
                  <button
                    type="button"
                    className="cursor-pointer self-start justify-self-start border-none border-current bg-transparent p-0 text-left font-mono font-semibold text-text wrap-anywhere before:text-muted before:content-['▸_'] max-fold:min-h-(--ui-tap) hover:underline aria-expanded:before:content-['▾_']"
                    aria-expanded={expanded}
                    aria-controls={expanded ? historyId : undefined}
                    onClick={() => onOpenChange(expanded ? null : attribute.name)}
                  >
                    {attribute.name}
                  </button>
                  <div className="flex min-w-0 flex-col gap-1">
                    <p className="whitespace-pre-wrap wrap-anywhere">{attribute.value}</p>
                    <span className="text-meta text-muted">
                      <RelativeTime value={attribute.updated_at} />
                    </span>
                  </div>
                </div>
                {expanded ? (
                  <AttributeHistory
                    holder={holder}
                    attribute={attribute}
                    canWrite={canWrite}
                    id={historyId}
                  />
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
 * История одного атрибута: записи дела проекта или области о нём, по порядку номеров — заведение,
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
  holder,
  attribute,
  canWrite,
  id,
}: {
  holder: Holder;
  attribute: ProjectAttribute;
  canWrite: boolean;
  id: string;
}) {
  const name = attribute.name;
  const feed = useInfiniteQuery(holderCaseQueryOptions(holder, { attribute: name }));
  const { t } = useTranslation('project');
  const { t: tArea } = useTranslation('area');

  const history = feed.data?.pages.flatMap((page) => page.items) ?? [];

  return (
    <div
      id={id}
      role="region"
      aria-label={t('history', { name })}
      className="flex flex-col gap-2 pt-1"
    >
      {/* Правка и снятие — первым блоком открытой истории, а не под каждой строкой. */}
      {canWrite ? (
        <div className="flex flex-wrap gap-2">
          <ChangeAttribute holder={holder} attribute={attribute} />
          <RemoveAttribute holder={holder} attribute={attribute} />
        </div>
      ) : null}
      {feed.data === undefined ? (
        <QueryState query={feed} loading={t('historyLoading')} />
      ) : history.length === 0 && !feed.hasNextPage ? (
        <p className="text-muted italic">
          {holder.kind === 'area' ? tArea('attributes.historyEmpty') : t('historyEmpty')}
        </p>
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
