import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useInfiniteQuery } from '@tanstack/react-query';
import { NotebookPen } from 'lucide-react';
import { useSearchParams } from 'react-router';
import {
  CaseFilters,
  EmptyByTypesNotice,
  EntryIndex,
  HiddenByTypeNotice,
  headingOfEntry,
  holderCaseQueryOptions,
  readEntryTypes,
} from '@/entities/entry';
import { Button, QueryState } from '@/shared/ui';
import type { Holder } from '../api/projects';
import { keepCaseTab } from '../model/holder-tab';
import { EntryForm } from './entry-form';

/** Блок-список: без своих полей, строки описи идут до краёв поверхности. */
const LIST_BLOCK = 'flex flex-col gap-0 rounded-control border border-line bg-surface';

/** Заголовок блока-списка: поля и линия под ним — у него, у блока их нет. */
const BLOCK_HEAD = 'flex flex-wrap items-baseline gap-3 border-b border-b-line px-3 pt-3 pb-2';

interface CaseSectionProps {
  /** Чьё дело: проекта или его области (TRK-557). */
  holder: Holder;
  /** Писать записи в дело: запись открыта всем (`useProjectRights`). */
  canWrite: boolean;
  /** Раскрытая запись из адреса (`?entry=N`): ссылка `TRK#7` или `TRK/promotion#3` — сюда. */
  openAt: number | null;
  onOpenChange: (no: number | null) => void;
}

/**
 * Дело проекта или области описью: та же `EntryIndex`, что у карточки задачи, с
 * владельцем-проектом или владельцем-областью. Раздел живёт в действиях по той же
 * причине, что атрибуты (`AttributesSection`): его рисуют два экрана.
 *
 * Описи в ответе проекта нет — строки собираются из записей дела (`headingOfEntry`), а
 * тело по клику читается отдельно адресом записи, как у задачи: опись не обещает, что
 * тело уже в памяти, и держать два пути к одному телу незачем.
 */
export function CaseSection({ holder, canWrite, openAt, onOpenChange }: CaseSectionProps) {
  const [searchParams, setSearchParams] = useSearchParams();
  /*
   * Отбор по типу живёт в адресе, как на экране «Дело» задачи: повторяющийся `?type=`.
   * Бэкенд получает его параметром `types`; пустой отбор уходит без параметра — все
   * записи. Остальные параметры адреса (`tab`, `entry`, `attribute`) отбор не трогает.
   */
  const types = useMemo(() => readEntryTypes(searchParams.getAll('type')), [searchParams]);
  const feed = useInfiniteQuery(holderCaseQueryOptions(holder, types.length > 0 ? { types } : {}));
  const [writing, setWriting] = useState(false);
  const noteButton = useRef<HTMLButtonElement>(null);
  const formPlace = useRef<HTMLDivElement>(null);
  const opened = useRef(false);
  const { t } = useTranslation('project');
  const { t: tArea } = useTranslation('area');
  const area = holder.kind === 'area';
  const headingId = `${holder.kind}-case`;

  /*
   * Кнопка «Написать заметку» уступает место форме, как у замечания к задаче, — и фокус
   * не должен пропасть вместе с ней: открытая форма получает его в поле, закрытая
   * возвращает на кнопку. Без этого человек с клавиатуры после каждого шага начинал бы
   * страницу сначала. Первая отрисовка фокус не трогает: её никто не просил.
   */
  useEffect(() => {
    if (writing) {
      opened.current = true;
      formPlace.current?.querySelector('textarea')?.focus();
    } else if (opened.current) {
      noteButton.current?.focus();
    }
  }, [writing]);
  const { t: brick } = useTranslation('ui');

  const entries = feed.data?.pages.flatMap((page) => page.items) ?? [];
  const index = entries.map(headingOfEntry);

  function changeTypes(next: string[]) {
    setSearchParams(
      (current) => {
        const updated = new URLSearchParams(current);
        updated.delete('type');
        for (const type of next) updated.append('type', type);
        // Отбор — правка открытой вкладки «Дело», а не уход с неё (TRK-618): если
        // без него правило адреса открыло бы другую вкладку, в адрес встаёт `tab=case`.
        return keepCaseTab(updated, holder.kind);
      },
      { replace: true },
    );
  }

  /*
   * Запись из адреса не должна прятаться отбором, оставшимся от прошлого чтения
   * (ссылки `TRK#7` типа не несут): если её нет в отобранной выдаче — об этом сказано
   * словами, со сбросом, как на экране «Дело» задачи.
   */
  const hidden =
    types.length > 0 &&
    openAt !== null &&
    feed.data !== undefined &&
    !feed.isFetching &&
    !feed.hasNextPage &&
    !entries.some((entry) => entry.no === openAt);
  const reference = `${holder.key}#${openAt}`;

  return (
    <section className={LIST_BLOCK} aria-labelledby={headingId}>
      <div className={BLOCK_HEAD}>
        <h2 className="text-screen" id={headingId}>
          {area ? tArea('case.title') : t('case')}
        </h2>
        {/* Число — только у дочитанного дела: у недочитанного оно было бы числом
            подгруженных страниц, а не записей, и врало бы тихо. */}
        {feed.data !== undefined && !feed.hasNextPage && index.length > 0 ? (
          <span className="text-meta text-muted">
            {brick('index.count', { count: index.length })}
          </span>
        ) : null}
        {canWrite && !writing ? (
          <Button ref={noteButton} size="sm" className="ml-auto" onClick={() => setWriting(true)}>
            <NotebookPen className="size-(--ui-mark)" aria-hidden="true" />
            {area ? tArea('entry.open') : t('note.open')}
          </Button>
        ) : null}
      </div>

      {/* Форма — под заголовком дела, над описью: заметку пишут, глядя на то, что уже
          подшито, и подтверждение встаёт на её место. */}
      {writing ? (
        <div ref={formPlace} className="border-b border-b-line px-3 py-3">
          <EntryForm holder={holder} onCancel={() => setWriting(false)} />
        </div>
      ) : null}

      <div className="border-b border-b-line px-3 py-2">
        <CaseFilters selected={types} onChange={changeTypes} />
      </div>

      {hidden ? (
        <div className="px-3 py-2">
          <HiddenByTypeNotice reference={reference} onReset={() => changeTypes([])} />
        </div>
      ) : null}

      {feed.data === undefined ? (
        <div className="px-3 py-2">
          <QueryState query={feed} loading={area ? tArea('case.loading') : t('caseLoading')} />
        </div>
      ) : (
        <>
          {types.length > 0 && index.length === 0 ? (
            <div className="px-3 py-2">
              {/* Сброс — в строке состояния фильтра, как на экране «Дело» задачи. */}
              <EmptyByTypesNotice />
            </div>
          ) : (
            <EntryIndex owner={holder} index={index} openAt={openAt} onOpenChange={onOpenChange} />
          )}
          {feed.hasNextPage ? (
            <div className="px-3 py-2">
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
        </>
      )}
    </section>
  );
}
