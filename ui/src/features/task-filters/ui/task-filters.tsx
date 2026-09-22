import { useEffect, useId, useRef, useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { ARCHIVE_AFTER_DAYS } from '@/entities/task';
import { ArrowDownUp, Code, ListFilter, Search, X } from 'lucide-react';
import { cn } from '@/shared/lib';
import { Button, Popover, PopoverContent, PopoverTrigger, Select } from '@/shared/ui';
import { TASK_SORTS, type TaskFilters } from '../model/filters';
import { type QueryProblem } from '../model/query-problem';
import { CONDITION_RESET, describeFilters } from '../model/summary';
import { FIELD, FIELD_PENDING } from './field';
import { FilterMenu } from './filter-menu';
import { PendingMark, QueryProblemHint } from './query-problem-hint';

interface TaskFiltersFormProps {
  filters: TaskFilters;
  onApply: (changes: Partial<TaskFilters>) => void;
  onReset: () => void;
  /** Отказ разбора отбора: показывается под полем запроса, а не поверх таблицы. */
  problem: QueryProblem | null;
}

/** Текстовые поля до отправки: они применяются по Enter, а не по каждой букве. */
interface Draft {
  assignee: string;
  text: string;
  query: string;
}

/**
 * Отбор задач: строка инструментов и строка того, что включено сейчас.
 *
 * Ничего не разворачивается: поиск по тексту стоит в строке всегда, остальные условия
 * добавляются из панели «Фильтр» за один-два щелчка, а включённые названы чипами под
 * строкой — поимённо и целиком. Список, в котором часть условий спрятана, человек
 * принял бы за все задачи.
 *
 * Язык запросов — отдельный режим той же строки, а не поле рядом с простым отбором:
 * заполненный запрос отменяет простой отбор целиком (`filtersToListParams`), и два
 * способа сказать одно и то же рядом спорили бы друг с другом.
 */
export function TaskFiltersForm({ filters, onApply, onReset, problem }: TaskFiltersFormProps) {
  // На доске статус — это столбец: отбора по статусу в панели там нет. Из адреса он не
  // стёрт и вернётся с таблицей.
  const board = filters.view === 'board';
  const applied = filters.query.trim() !== '';

  const [draft, setDraft] = useState(() => toDraft(filters));
  /*
   * Режим запроса включается кнопкой ещё до того, как в поле что-то напечатано, — это
   * состояние экрана, а не выдачи. Заполненный запрос держит режим сам: ссылка с
   * запросом и отказ его разбора обязаны открыться с полем на экране.
   */
  const [queryChosen, setQueryChosen] = useState(applied);
  const querying = queryChosen || applied;
  const [menuOpen, setMenuOpen] = useState(false);
  const archiveHintId = useId();
  /*
   * Кнопка «Фильтр» — якорь фокуса. Снятый чип исчезает вместе со своей кнопкой, и фокус
   * улетал бы на `body`: следующий Tab начинал бы обход страницы с начала.
   */
  const menuRef = useRef<HTMLButtonElement>(null);
  const { t } = useTranslation('tasks');

  // Отбор меняется и мимо формы: «сбросить», кнопка «назад», открытая ссылка.
  useEffect(() => {
    setDraft(toDraft(filters));
  }, [filters]);

  const conditions = describeFilters(filters, t);
  const archiveHint = t('filters.archive.hint', { count: ARCHIVE_AFTER_DAYS });
  const pending = pendingFields(draft, filters);

  /**
   * Любое изменение отбора отправляет и напечатанное, но ещё не применённое.
   * Иначе переключатель, нажатый после набора текста, молча стирал бы этот текст:
   * в адрес он не попал, а поле перечиталось бы из адреса.
   */
  function applyWith(changes: Partial<TaskFilters>) {
    onApply({
      assignee: draft.assignee,
      text: draft.text,
      query: draft.query,
      ...changes,
    });
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    applyWith({});
  }

  /** Выход из режима запроса снимает запрос: простой отбор возвращается таким, каким был. */
  function toggleQuery() {
    if (querying) {
      setQueryChosen(false);
      if (applied || draft.query !== '') applyWith({ query: '' });
    } else {
      setQueryChosen(true);
    }
  }

  return (
    <section className="flex flex-col gap-2" aria-label={t('filters.label')}>
      {/* Строка инструментов: чем отбирать. */}
      <div className="flex flex-wrap items-center gap-2">
        {querying ? (
          <QueryForm
            value={draft.query}
            pending={pending.query}
            problem={problem}
            focus={queryChosen && !applied}
            onChange={(query) => setDraft({ ...draft, query })}
            onSubmit={submit}
          />
        ) : (
          <>
            <form className="flex min-w-0 grow basis-56" role="search" onSubmit={submit}>
              <SearchField
                value={draft.text}
                pending={pending.text}
                onChange={(text) => setDraft({ ...draft, text })}
              />
            </form>

            <Popover open={menuOpen} onOpenChange={setMenuOpen}>
              <PopoverTrigger asChild>
                <Button ref={menuRef} tone="quiet" size="sm">
                  <ListFilter className="size-(--ui-mark)" aria-hidden="true" />
                  {t('filters.menu')}
                  {/*
                   * Число условий на кнопке — чтобы связать её с чипами под строкой. Глазам
                   * хватает цифры, диктору чипы и так называют всё списком.
                   */}
                  {conditions.length === 0 ? null : (
                    <span
                      className="grid min-w-4 place-items-center rounded-pill bg-accent px-1 text-label leading-[1.4] text-accent-text"
                      aria-hidden="true"
                    >
                      {conditions.length}
                    </span>
                  )}
                </Button>
              </PopoverTrigger>
              <PopoverContent className="w-96" aria-label={t('filters.menuLabel')}>
                <FilterMenu
                  filters={filters}
                  board={board}
                  assignee={draft.assignee}
                  pending={pending.assignee}
                  onAssignee={(assignee) => setDraft({ ...draft, assignee })}
                  onApply={applyWith}
                />
              </PopoverContent>
            </Popover>
          </>
        )}

        {/*
         * Порядок стоит в строке, видимой всегда, и в обоих видах: на доске он упорядочивает
         * карточки внутри столбцов (UI-130#10). Подпись поля скрыта в `aria-label`, а что
         * это порядок, говорит знак: подпись вроде «сначала живые в деле» сама его не
         * называет.
         */}
        <Select
          className="whitespace-nowrap"
          label={t('filters.sort.label')}
          icon={<ArrowDownUp className="size-(--ui-mark) shrink-0 text-faint" aria-hidden="true" />}
          value={filters.sort}
          onValueChange={(sort) => applyWith({ sort })}
          options={TASK_SORTS.map((option) => ({
            value: option,
            label: t(`filters.sort.${option}`),
          }))}
        />

        <Button
          tone="quiet"
          size="sm"
          // Включённый режим виден и глазу: кнопка «нажата» тем же тоном, что включённое
          // значение в панели.
          className="aria-pressed:border-accent aria-pressed:bg-accent-soft"
          aria-pressed={querying}
          onClick={toggleQuery}
        >
          <Code className="size-(--ui-mark)" aria-hidden="true" />
          {t('filters.query.toggle')}
        </Button>
      </div>

      {/* Строка состояния: что отобрано сейчас. */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        {querying ? (
          <p className="text-meta text-muted">{t('filters.query.note')}</p>
        ) : (
          /* Список, а не абзац: программа чтения с экрана называет число условий вслух. */
          <ul
            className="flex min-w-0 list-none flex-wrap items-center gap-1.5 p-0"
            aria-label={t('filters.conditions')}
          >
            {conditions.length === 0 ? (
              /*
               * Без условий выдача всё равно отобрана, пока архив скрыт: «показаны все
               * задачи» было бы выводом обо всём по отобранной выдаче (`docs/notes/ui.md`).
               */
              <li className="text-meta text-muted">
                {filters.showArchive ? t('filters.allShown') : t('filters.allButArchive')}
              </li>
            ) : (
              conditions.map((condition) => (
                /*
                 * Чип — две соседние мишени, а не кнопка в кнопке: текст открывает панель
                 * фильтра, крестик снимает условие.
                 */
                <li
                  key={condition.id}
                  className="inline-flex items-center rounded-pill bg-accent-soft text-mark whitespace-nowrap text-text"
                >
                  <button
                    type="button"
                    className={cn(CHIP_PART, 'py-0.5 pr-1 pl-2.5')}
                    onClick={() => setMenuOpen(true)}
                  >
                    {condition.label}
                  </button>
                  <button
                    type="button"
                    className={cn(CHIP_PART, 'mr-0.5 grid size-5 place-items-center text-muted')}
                    aria-label={t('filters.remove', { condition: condition.label })}
                    onClick={() => {
                      applyWith(CONDITION_RESET[condition.id]);
                      menuRef.current?.focus();
                    }}
                  >
                    <X className="size-(--ui-mark)" aria-hidden="true" />
                  </button>
                </li>
              ))
            )}
          </ul>
        )}

        {querying || conditions.length === 0 ? null : (
          <button type="button" className={RESET} onClick={onReset}>
            {t('filters.reset')}
          </button>
        )}

        {/*
         * Архив — умолчание списка, а не условие (UI-97): чипом он не значится, крестиком
         * не снимается и сбросом не возвращается. Флажок стоит в строке того, что
         * показано, — рядом с фразой «все, кроме архива», которую он и меняет.
         */}
        <label
          className="ml-auto inline-flex items-center gap-1.5 text-meta whitespace-nowrap text-muted"
          title={archiveHint}
        >
          <input
            type="checkbox"
            className="size-(--ui-mark) accent-accent"
            checked={filters.showArchive}
            aria-describedby={archiveHintId}
            onChange={(event) => applyWith({ showArchive: event.target.checked })}
          />
          {t('filters.archive.label')}
        </label>
        <span id={archiveHintId} className="sr-only">
          {archiveHint}
        </span>
      </div>
    </section>
  );
}

/** Часть чипа: своя мишень с откликом на наведение и видимым фокусом. */
const CHIP_PART =
  'rounded-pill border-none bg-transparent leading-[1.4] transition-colors duration-(--motion-fast) ease-fast hover:bg-sunken hover:text-text focus-visible:outline-2 focus-visible:outline-focus';

/** Сброс — действие-ссылка в строке состояния, а не третья кнопка рядом с двумя. */
const RESET =
  'rounded-mark border-none bg-transparent p-0 text-meta text-muted underline underline-offset-2 hover:text-text focus-visible:outline-2 focus-visible:outline-focus';

/**
 * Поиск по тексту: самое частое условие стоит в строке всегда. Применяется по Enter —
 * поле стоит в форме поиска, и отдельного обработчика клавиши нет.
 */
function SearchField({
  value,
  pending,
  onChange,
}: {
  value: string;
  pending: boolean;
  onChange: (value: string) => void;
}) {
  const pendingId = useId();
  const { t } = useTranslation('tasks');

  return (
    <div className="relative flex min-w-0 grow items-center">
      <Search
        className="pointer-events-none absolute left-2 size-(--ui-mark) text-faint"
        aria-hidden="true"
      />
      <input
        type="search"
        className={cn(FIELD, 'pl-7', pending ? FIELD_PENDING : 'border-line-strong')}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={t('filters.textPlaceholder')}
        aria-label={t('filters.text')}
        aria-describedby={pending ? pendingId : undefined}
        autoComplete="off"
        spellCheck={false}
      />
      {pending ? <PendingMark id={pendingId} /> : null}
    </div>
  );
}

/**
 * Режим запроса: строка на языке бэкенда вместо поиска и панели фильтра. Применяется
 * по Enter или кнопкой; отказ разбора наложен под полем и указывает на символ.
 */
function QueryForm({
  value,
  pending,
  problem,
  focus,
  onChange,
  onSubmit,
}: {
  value: string;
  pending: boolean;
  problem: QueryProblem | null;
  /** Режим включён только что нажатой кнопкой: человек пришёл печатать. */
  focus: boolean;
  onChange: (value: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  const problemId = useId();
  const pendingId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const { t } = useTranslation('tasks');
  const describedBy = [problem === null ? null : problemId, pending ? pendingId : null].filter(
    (id) => id !== null,
  );

  // Только при появлении поля: дальше фокус принадлежит человеку.
  useEffect(() => {
    if (focus) inputRef.current?.focus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <form className="flex min-w-0 grow basis-72 items-center gap-2" onSubmit={onSubmit}>
      <div className="relative flex min-w-0 grow items-center">
        <input
          ref={inputRef}
          className={cn(
            FIELD,
            // Лигатуры Fira Code склеивают `>=` в «⩾»: человек напечатал бы то, чего
            // на экране не видит, а указатель отказа мерит символы строки, а не знаки.
            'font-mono text-meta [font-variant-ligatures:none]',
            pending ? FIELD_PENDING : 'border-line-strong',
            'aria-invalid:border-danger',
          )}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder={t('filters.query.placeholder')}
          aria-label={t('filters.query.label')}
          aria-invalid={problem !== null}
          aria-describedby={describedBy.length === 0 ? undefined : describedBy.join(' ')}
          autoComplete="off"
          spellCheck={false}
        />
        {pending ? <PendingMark id={pendingId} /> : null}
        {problem === null ? null : <QueryProblemHint id={problemId} problem={problem} />}
      </div>
      <Button type="submit" size="sm" disabled={!pending}>
        {t('filters.apply')}
      </Button>
    </form>
  );
}

/** Какие поля напечатаны, но ещё не применены: по ним рисуется признак черновика. */
function pendingFields(draft: Draft, filters: TaskFilters): Record<keyof Draft, boolean> {
  return {
    assignee: draft.assignee.trim() !== filters.assignee.trim(),
    text: draft.text.trim() !== filters.text.trim(),
    query: draft.query.trim() !== filters.query.trim(),
  };
}

function toDraft(filters: TaskFilters): Draft {
  return {
    assignee: filters.assignee,
    text: filters.text,
    query: filters.query,
  };
}
