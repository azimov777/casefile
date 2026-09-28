import { useMemo, useRef } from 'react';
import { Trans, useTranslation } from 'react-i18next';
import { Link } from 'react-router';
import { useQuery } from '@tanstack/react-query';
import { tasksQueryOptions, tasksTotalQueryOptions, type Task } from '@/entities/task';
import {
  TaskFiltersForm,
  filtersToListParams,
  hasConditions,
  readQueryProblem,
  useTaskFilters,
} from '@/features/task-filters';
import { UpdatesBar } from '@/features/live-journal';
import { ExplanationPanel, HINT_KEYS } from '@/features/manage-onboarding';
import { type Page } from '@/shared/api';
import { useLanguage } from '@/shared/i18n';
import { formatNumber } from '@/shared/lib';
import { Button, Callout, QueryState, type QueryLike } from '@/shared/ui';
import { TasksBoard } from './tasks-board';
import { TasksPagination } from './tasks-pagination';
import { TasksTable } from './tasks-table';

/**
 * Список задач в двух режимах: таблицей и доской по столбцам статусов. Строка выдачи
 * у них одна и та же, с признаками прямо в ней (`docs/FRONTEND.md`,
 * «Строка списка»), а вот читают они по-разному: таблица берёт страницу целиком,
 * а на доске каждый столбец читает свой отбор сам (UI-70). Экран поэтому держит для
 * доски только её число — сколько задач нашлось по отбору.
 *
 * Своего состояния у экрана нет: отбор, режим и номер страницы живут в адресе.
 */
export function TasksPage() {
  const { filters, apply, reset } = useTaskFilters();
  const { t } = useTranslation('tasks');
  const { language } = useLanguage();
  const board = filters.view === 'board';
  const params = useMemo(() => filtersToListParams(filters), [filters]);

  /*
   * Запроса всегда два, работает ровно один: хук нельзя позвать условно, а лишний
   * запрос в отключённом режиме означал бы два обращения к списку на одну отрисовку.
   *
   * У доски это запрос без задач — одна строка ради `meta.total`. Он отвечает на два
   * вопроса разом: сколько задач нашлось по отбору (ни один столбец этого не знает —
   * свёрнутый не читает вовсе) и разобрал ли бэкенд запрос, написанный человеком.
   * Второе объясняет форма отбора, и место, по которому она это делает, обязано быть
   * одно: шесть столбцов объяснили бы один и тот же отказ шесть раз.
   */
  const list = useQuery({ ...tasksQueryOptions(params), enabled: !board });
  const counted = useQuery({ ...tasksTotalQueryOptions(params), enabled: board });

  /**
   * Последняя удачная страница таблицы. Отказ разбора запроса не должен опустошать
   * таблицу: человек правит запрос, глядя на то, что нашлось до опечатки.
   * `placeholderData` этого не делает — он держит прошлые строки только на время
   * ожидания, а на отказе отдаёт пустоту.
   */
  const lastLoaded = useRef<Page<Task> | null>(null);
  if (list.data !== undefined) lastLoaded.current = list.data;
  const loaded = list.data ?? lastLoaded.current;

  const active = board ? counted : list;

  /*
   * Состояние запроса над содержимым. У таблицы это её запрос целиком, у доски —
   * запрос числа выдачи, но **без ожидания**: полоса «Загружаем задачи…», появившаяся
   * над доской и пропавшая через мгновение, сдвигает карточки в тот самый кадр,
   * в который человек в них смотрит (замерено: первая карточка `open` уезжала
   * на 58 px вверх). Своё ожидание каждый столбец рисует у себя, а отказ остаётся
   * здесь: он редок, и подвинуть ради него доску честно.
   */
  const state: QueryLike = board
    ? {
        isPending: false,
        isFetching: counted.isFetching,
        error: counted.error,
        refetch: () => void counted.refetch(),
      }
    : list;

  // Отказ разбора относится к полю запроса только тогда, когда запрос отправляли мы
  // из этого поля; негодное значение в адресе — беда всей страницы, а не поля.
  const problem =
    filters.query.trim() === '' ? null : readQueryProblem(active.error, filters.query);

  /**
   * Сколько задач нашлось по отбору. Список задач заполняет `meta.total` всегда
   * (TRK-41); `null` значит «не считали» — тогда ни числа выдачи, ни номеров страниц
   * не показывается, остаётся честное «есть ещё» по `has_more`.
   */
  const total = loaded?.meta?.total ?? null;
  const hasMore = loaded?.meta?.has_more === true;

  /*
   * Что за число стоит у заголовка — одно и то же в обоих режимах: сколько задач
   * нашлось по отбору. У доски оно раньше говорило про прочитанное и росло от нажатий
   * «Ещё»; теперь столбцы читают по мере прокрутки, и число прочитанного меняется
   * от того, куда человек доехал, — про выдачу оно не сказало бы ничего. Числа
   * по статусам стоят там, где им место: в заголовках столбцов.
   */
  const found = board ? (counted.data ?? null) : (total ?? loaded?.items.length ?? null);

  /**
   * Страница за концом выдачи: пересланная ссылка пережила сузившийся отбор. Бэкенд
   * отвечает на неё пустой страницей и прежним `total` — по нему и видно, что задачи
   * есть, просто не здесь.
   */
  const beyond = loaded?.items.length === 0 && total !== null && total > 0;

  /** Нет условий сверх проекта: первый, общий для обеих веток член правила ниже. */
  const noConditions = !hasConditions(filters);

  /**
   * Первая выдача уже пуста. Сама по себе эта пустота не решает ничего — по условиям
   * не нашлось или проект пуст вовсе, — но именно она отпирает второй запрос ниже:
   * спрашивать архив, пока в первой выдаче есть хоть что-то, незачем. У таблицы это
   * та же страница, что открывает пустую ветку разметки (`loaded`); у доски — то же
   * число, что уже спрошено ради заголовка (`counted`, через `found`).
   */
  const primaryEmpty = board ? found === 0 : loaded !== null && loaded.items.length === 0;

  /**
   * Второй запрос: тот же проект, архив показан, страница в одну строку — тот же
   * приём, что у числа над доской (`tasksTotalQueryOptions`). Раньше «скрывать
   * нечего» стояло эвристикой по `filters.showArchive` — человек проверял бы архив
   * сам нажатием «Показать архив» (TRK-365#10) — и оказалось неправдой ради того, от
   * кого текст и заводился: он не нажимает ничего и видит прежнюю подсказку (замечание
   * координатора, TRK-365#20). Второй вопрос бэкенду отвечает на то же самое честно, а
   * не гадает: правило архива (`entities/task/model/archive.ts`) прячет только
   * закрытые задачи, и спрятал ли оно хоть одну, здесь спрашивают напрямую.
   *
   * Уходит он не всегда: пока в первой выдаче есть что-то, пока архив уже показан
   * (тогда первая выдача и есть весь ответ) или пока у отбора есть условие сверх
   * проекта (тогда пустота — про условие, а не про архив), спрашивать нечего.
   */
  const archiveCheckEnabled = noConditions && !filters.showArchive && primaryEmpty;
  const archiveCheck = useQuery({
    ...tasksTotalQueryOptions({ project: filters.project === '' ? undefined : [filters.project] }),
    enabled: archiveCheckEnabled,
  });

  /**
   * Пустой проект, а не пустая выдача по условиям: у отбора нет условий сверх
   * проекта, и — архив уже показан, тогда сказать «задач по этим условиям нет» и
   * предложить сбросить нечего сбрасывать было бы неправдой о причине (TRK-360#9), —
   * или архив ещё скрыт, но второй запрос уже проверил его и нашёл там пусто. Пока
   * второй запрос не ответил или ответил отказом, `noTasksYet` остаётся ложным —
   * интерфейс не утверждает того, чего не может знать, и виден прежний текст
   * с подсказкой об архиве (TRK-377).
   */
  const noTasksYet =
    noConditions && (filters.showArchive || (archiveCheck.isSuccess && archiveCheck.data === 0));

  return (
    <main className="flex flex-col gap-3">
      {/* Пояснение экрана — первым блоком содержимого (TRK-363). Список и доска — два
          пояснения с разными ключами: закрытое на одном вида другого не закрывает. */}
      <ExplanationPanel hintKey={board ? HINT_KEYS.board : HINT_KEYS.tasks}>
        {t(board ? 'explanation.board' : 'explanation.list')}
      </ExplanationPanel>

      {/*
       * Полоса обновлений — принадлежность таблицы, а не экрана: там перестановка строк
       * под курсором это шум, и живой поток копит изменения, предлагая их нажатием.
       * Доска обновляется сама (UI-72), и полосе над ней делать нечего — предлагать
       * показать то, что уже показано, значит врать про состояние экрана.
       *
       * По той же причине полоса молчит, пока таблица читается: накопленное до начала
       * чтения придёт в ответе (UI-95). `isFetching` здесь оптимистический — он стоит
       * уже в отрисовке, после которой чтение начнётся, и на приходе с доски полоса
       * не мелькает.
       *
       * Полоса стоит вне потока вёрстки — строки от её появления не двигаются.
       */}
      {board ? null : <UpdatesBar reading={list.isFetching} />}

      {/*
       * Заголовок, отбор и переключатель режима — одной строкой. Тремя блоками друг
       * под другом они уводили первую строку таблицы на 415-й пиксель: из двадцати
       * одной задачи на экране оставалось семь.
       *
       * Выравнивание по верху, а не по центру: заголовок стоит вровень со строкой
       * инструментов отбора, а строка состояния под ней его не тянет вниз.
       */}
      <div className="flex flex-wrap items-start gap-3">
        <h1 className="flex items-baseline gap-2 text-screen leading-[1.9]">
          {t('title')}
          {/*
           * Число выдачи стоит здесь, а не полосой над таблицей. Из имени заголовка оно
           * скрыто: то же число программа чтения с экрана берёт из области ниже
           * («Найдено задач: 98»), а «Задачи 98» вместо «Задачи» ломало бы навигацию
           * по заголовкам. Подпись таблицы говорит своё и другое — сколько строк
           * на этой странице.
           */}
          {found === null ? null : (
            <span className="text-label font-normal text-muted" aria-hidden="true">
              {formatNumber(found, language)}
            </span>
          )}
        </h1>
        {/*
         * Колонка отбора занимает всё, что осталось от заголовка, но не меньше 24rem
         * (`basis-96`). `min-w-0` обязателен: без него элемент гибкой раскладки не
         * сжимается меньше своего содержимого, и при увеличенном вдвое тексте основа
         * в 24rem становится шире узкого экрана — строка условий расширяет документ
         * вместо того, чтобы перенестись.
         */}
        <div className="min-w-0 grow basis-96">
          <TaskFiltersForm filters={filters} onApply={apply} onReset={reset} problem={problem} />
        </div>
      </div>

      {/*
       * Смена отбора объявляется вслух: человек с программой чтения с экрана иначе
       * не узнаёт, что выдача пересобралась, — фокус остался на чипе или флажке, а
       * таблица под ним стала другой. Область постоянная: `aria-live` объявляет только
       * то, что появилось внутри уже существующего контейнера.
       */}
      <p aria-live="polite" className="sr-only">
        {found === null ? '' : t('found', { count: found })}
      </p>

      {/*
       * Отказ разбора запроса объясняет форма, у самого поля: там же сказано и то,
       * что в таблице остались строки предыдущего отбора. Полосы над таблицей нет
       * намеренно — она сдвигала бы строки вниз ровно тогда, когда человек правит
       * запрос и сверяется с ними. Всё остальное — общее состояние запроса с повтором.
       */}
      {problem === null ? <QueryState query={state} loading={t('loading')} /> : null}

      {board ? (
        <>
          {/*
           * Доска не читает задач сама (см. комментарий класса выше) и потому не
           * узнаёт о пустом проекте от столбцов — каждый из них видел бы только
           * свой статус. Число уже спрошено ради заголовка (`counted`), а «скрывать
           * ли архив нечего» — вторым запросом выше (`archiveCheck`, TRK-377): то же
           * самое различение здесь стоит над доской, а не заменяет её — свёрнутые
           * и раскрытые столбцы остаются на месте.
           */}
          {noTasksYet && found === 0 ? <NoTasksYetCallout /> : null}
          <TasksBoard
            params={params}
            explained={problem !== null}
            collapsed={filters.collapsed}
            onToggle={(status, open) =>
              apply({
                collapsed: open
                  ? filters.collapsed.filter((value) => value !== status)
                  : [...filters.collapsed, status],
              })
            }
          />
        </>
      ) : loaded === null ? null : loaded.items.length === 0 ? (
        /*
         * Пустая страница бывает двух разных бед, и путать их нельзя: по этим условиям
         * задач нет вовсе — или они есть, но кончились раньше этой страницы. Второе
         * лечится не сбросом отбора, а возвратом на существующую страницу, и ряд
         * страниц под сообщением как раз туда и ведёт.
         */
        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-3">
            {beyond ? (
              <Callout>{t('beyond', { count: total ?? 0 })}</Callout>
            ) : noTasksYet ? (
              <NoTasksYetCallout />
            ) : (
              <>
                <Callout>{t('empty')}</Callout>
                {/*
                 * Пока архив скрыт, «задач нет» — вывод о выдаче без архива, а не о
                 * проекте: закрытые давно могут быть здесь же. Сказать об этом и дать
                 * показать их — то же правило, что у пустой входящей с отбором.
                 */}
                {filters.showArchive ? null : (
                  <>
                    <span className="text-meta text-muted">{t('archiveHidden')}</span>
                    <Button tone="quiet" onClick={() => apply({ showArchive: true })}>
                      {t('showArchive')}
                    </Button>
                  </>
                )}
                <Button tone="quiet" onClick={reset} disabled={!hasConditions(filters)}>
                  {t('resetFilters')}
                </Button>
              </>
            )}
          </div>
          <TasksPagination page={filters.page} total={total} hasMore={hasMore} />
        </div>
      ) : (
        <>
          <TasksTable tasks={loaded.items} stale={list.isFetching || problem !== null} />

          <TasksPagination page={filters.page} total={total} hasMore={hasMore} />
        </>
      )}
    </main>
  );
}

/**
 * «Задач ещё нет»: их заводит и ведёт агент, а дорога к тому, что сказать ему, —
 * экран «Начало» (`/start`). Ссылка ведёт туда адресом, а не подпиской на
 * маршрут — сам экран заводит соседняя задача (TRK-361), и здесь его нет.
 *
 * Разметка ссылки живёт в словаре тегом `<start>` (тот же приём, что у
 * `connect-page.tsx`, `token.ownToken`): порядок слов вокруг неё в двух языках
 * разный, и склеивать его из кусков `t()` в разметке нельзя.
 */
function NoTasksYetCallout() {
  const { t } = useTranslation('tasks');

  return (
    <Callout>
      <Trans t={t} i18nKey="noneYet" components={{ start: <Link to="/start" /> }} />
    </Callout>
  );
}
