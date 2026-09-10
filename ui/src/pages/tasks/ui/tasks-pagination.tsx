import { useSearchParams } from 'react-router';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import { TASK_PAGE_SIZE } from '@/entities/task';
import { tasksHref } from '@/features/task-filters';
import { PAGE_GAP, pageCount, pageWindow } from '@/shared/lib';
import {
  Pagination,
  PaginationGap,
  PaginationItem,
  PaginationLink,
  PaginationNext,
  PaginationPrevious,
} from '@/shared/ui';

interface TasksPaginationProps {
  /** Открытая страница, с 1. Живёт в адресе — сюда приходит уже прочитанной оттуда. */
  page: number;
  /** Сколько задач нашлось по отбору (`meta.total`); `null` — бэкенд не считал. */
  total: number | null;
  /** `meta.has_more`. Нужен ровно тогда, когда общего числа нет и считать нечего. */
  hasMore: boolean;
}

/**
 * Ряд страниц под таблицей: `◀ 1 2 [3] 4 … 7 ▶`.
 *
 * Число страниц — `ceil(total / limit)` по полям ответа (TRK-41), а не догадка по
 * `has_more`. Поэтому и поведение при `total: null` другое: номеров нет вовсе,
 * остаются шаг назад и шаг вперёд, а «вперёд» ведёт, пока бэкенд говорит `has_more`.
 * Честное «есть ещё» лучше выдуманного числа страниц (`docs/notes/ui.md`, «Вывод обо
 * всём по отобранной выдаче»).
 *
 * Каждая ступень — ссылка на тот же список с другим `page` в адресе, собранная общим
 * `tasksHref`: второго способа собрать адрес списка в приложении нет.
 */
export function TasksPagination({ page, total, hasMore }: TasksPaginationProps) {
  const [searchParams] = useSearchParams();
  const { t } = useTranslation('tasks');
  const href = (number: number) => tasksHref(searchParams, { page: number });

  const pages = total === null ? null : pageCount(total, TASK_PAGE_SIZE);

  // Одна страница — листать нечего, и ряд из единственной кнопки был бы приглашением
  // никуда. Ссылка на несуществующую страницу — исключение: с неё надо чем-то
  // вернуться, и возвращает как раз ряд.
  //
  // Пустая выдача — не исключение: страниц у неё ноль, вести ряду некуда, и объясняет
  // её не он, а сообщение над ним.
  if (pages === 0) return null;
  if (pages !== null && pages <= 1 && page <= pages) return null;
  if (pages === null && page === 1 && !hasMore) return null;

  /*
   * Шаг назад со страницы за концом выдачи ведёт на последнюю существующую, а не на
   * соседний по счёту номер: с девяносто девятой страницы «назад» на девяносто восьмую
   * уводило бы из пустоты в пустоту.
   */
  const previous = page > 1 ? href(Math.min(page - 1, pages ?? page - 1)) : null;
  const next =
    pages === null ? (hasMore ? href(page + 1) : null) : page < pages ? href(page + 1) : null;

  return (
    <div className="flex flex-wrap items-center gap-3">
      <Pagination label={t('paging.label')}>
        <PaginationItem>
          <PaginationPrevious to={previous} label={t('paging.previous')} />
        </PaginationItem>

        {(pages === null ? [page] : pageWindow(page, pages)).map((slot, index) =>
          slot === PAGE_GAP ? (
            // Ключ по месту в ряду: пропуск не переезжает внутри одной отрисовки,
            // а от страницы к странице ряд всё равно собирается заново.
            <PaginationGap key={`gap-${index}`} />
          ) : (
            <PaginationItem key={slot}>
              <PaginationLink
                to={href(slot)}
                current={slot === page}
                label={t('paging.page', { page: slot })}
              >
                {slot}
              </PaginationLink>
            </PaginationItem>
          ),
        )}

        <PaginationItem>
          <PaginationNext to={next} label={t('paging.next')} />
        </PaginationItem>
      </Pagination>

      {/*
       * Ряд цифр под таблицей сам по себе не называет себя: словами сказано, что это
       * страницы и сколько их. Диктору то же самое говорит `aria-current` на открытой
       * ступени, поэтому подпись от него скрыта — иначе он прочёл бы это дважды.
       */}
      <span className="text-label text-muted" aria-hidden="true">
        {pageLabel(page, pages, t)}
      </span>
    </div>
  );
}

/** Подпись ряда. Страница за концом выдачи не называется существующей. */
function pageLabel(page: number, pages: number | null, t: TFunction<'tasks'>): string {
  if (pages === null) return t('paging.page', { page });
  if (page > pages) return t('paging.total', { count: pages });
  return t('paging.pageOf', { page, pages });
}
