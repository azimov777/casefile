import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useInfiniteQuery } from '@tanstack/react-query';
import { NotebookPen } from 'lucide-react';
import { EntryIndex, headingOfEntry, projectCaseQueryOptions } from '@/entities/entry';
import { NoteForm } from '@/features/manage-project';
import { Button, QueryState } from '@/shared/ui';

/** Блок-список: без своих полей, строки описи идут до краёв поверхности. */
const LIST_BLOCK = 'flex flex-col gap-0 rounded-control border border-line bg-surface';

/** Заголовок блока-списка: поля и линия под ним — у него, у блока их нет. */
const BLOCK_HEAD = 'flex flex-wrap items-baseline gap-3 border-b border-b-line px-3 pt-3 pb-2';

interface ProjectCaseProps {
  projectKey: string;
  /** Писать заметки в дело: любой набор ключа (`useProjectRights`). */
  canWrite: boolean;
  /** Раскрытая запись из адреса (`?entry=N`): ссылка `TRK#7` приходит сюда. */
  openAt: number | null;
  onOpenChange: (no: number | null) => void;
}

/**
 * Дело проекта описью: та же `EntryIndex`, что у карточки задачи, с владельцем-проектом.
 *
 * Описи в ответе проекта нет — строки собираются из записей дела (`headingOfEntry`), а
 * тело по клику читается отдельно адресом записи, как у задачи: опись не обещает, что
 * тело уже в памяти, и держать два пути к одному телу незачем.
 */
export function ProjectCase({ projectKey, canWrite, openAt, onOpenChange }: ProjectCaseProps) {
  const feed = useInfiniteQuery(projectCaseQueryOptions(projectKey));
  const [writing, setWriting] = useState(false);
  const noteButton = useRef<HTMLButtonElement>(null);
  const formPlace = useRef<HTMLDivElement>(null);
  const opened = useRef(false);
  const { t } = useTranslation('project');

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

  return (
    <section className={LIST_BLOCK} aria-labelledby="project-case">
      <div className={BLOCK_HEAD}>
        <h2 className="text-screen" id="project-case">
          {t('case')}
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
            {t('note.open')}
          </Button>
        ) : null}
      </div>

      {/* Форма — под заголовком дела, над описью: заметку пишут, глядя на то, что уже
          подшито, и подтверждение встаёт на её место. */}
      {writing ? (
        <div ref={formPlace} className="border-b border-b-line px-3 py-3">
          <NoteForm projectKey={projectKey} onCancel={() => setWriting(false)} />
        </div>
      ) : null}

      {feed.data === undefined ? (
        <div className="px-3 py-2">
          <QueryState query={feed} loading={t('caseLoading')} />
        </div>
      ) : (
        <>
          <EntryIndex
            owner={{ kind: 'project', key: projectKey }}
            index={index}
            openAt={openAt}
            onOpenChange={onOpenChange}
          />
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
