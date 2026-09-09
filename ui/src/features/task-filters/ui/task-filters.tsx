import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from 'react';
import { TASK_PRIORITIES, TASK_STATUSES } from '@/entities/task';
import { X } from 'lucide-react';
import { cn, useExitHold } from '@/shared/lib';
import { Button, Reveal, Select } from '@/shared/ui';
import { TASK_SORTS, type TaskFilters } from '../model/filters';
import { useFiltersExpanded } from '../model/expanded';
import { caretLine, type QueryProblem } from '../model/query-problem';
import { CONDITION_RESET, describeFilters } from '../model/summary';

interface TaskFiltersFormProps {
  filters: TaskFilters;
  onApply: (changes: Partial<TaskFilters>) => void;
  onReset: () => void;
  /** Отказ разбора отбора: показывается под полем запроса, а не поверх таблицы. */
  problem: QueryProblem | null;
}

/** Текстовые поля до отправки: они применяются по «Применить», а не по каждой букве. */
interface Draft {
  assignee: string;
  text: string;
  query: string;
}

/*
 * Повторяющиеся строки утилит названы, а не скопированы, — по образцу `WIDTHS`
 * в `tasks-table.tsx`. Флажок стоит в разметке пять раз, строка формы три, подпись
 * и сноска по два: копия расходится с оригиналом при первой же правке одного из мест.
 */

/** Флажок отбора: подпись и квадрат стоят в строку и не переносятся посередине. */
const CHECK = 'inline-flex items-center gap-1 text-body whitespace-nowrap';

/** Идентификатор контракта внутри флажка: он мельче подписи рядом. */
const CODE = 'font-mono text-meta';

/** Строка формы: поля в ней разной высоты и выравниваются по нижнему краю. */
const LINE = 'flex flex-wrap items-end gap-3';

/** Подпись поля и легенда набора флажков. */
const LABEL = 'text-label text-muted';

/** Набор флажков в рамке: рамка называет, что статусы и приоритеты — один вопрос. */
const GROUP =
  'flex flex-wrap items-center gap-x-3 gap-y-1 rounded-mark border border-line px-2 pt-0 pb-1';

/*
 * Сноска у подписи и примечание доски: одна строка на оба места, потому что в CSS
 * это был один класс. `self-center` здесь не украшение — в строке подписи оно снимает
 * выравнивание по базовой линии, а в колонке формы ставит примечание по центру.
 */
const NOTE = 'self-center text-meta text-muted italic';

/**
 * Отбор задач: строка с тем, что включено сейчас, и форма под ней.
 *
 * Свёрнута по умолчанию — первый экран списка принадлежит задачам. Свёрнутый вид не
 * прячет отбор, а называет его словами целиком: список, в котором часть условий
 * спрятана, человек принял бы за все задачи.
 */
export function TaskFiltersForm({ filters, onApply, onReset, problem }: TaskFiltersFormProps) {
  // На доске статус — это столбец, а порядок задан её устройством. Показывать поля,
  // которые сейчас ни на что не влияют, значит врать: они спрятаны, но из адреса
  // не стёрты и вернутся вместе с таблицей.
  const board = filters.view === 'board';

  const [draft, setDraft] = useState(() => toDraft(filters));
  // Отказ разбора держит форму раскрытой: поле, в котором сделана опечатка, обязано
  // быть на экране рядом с объяснением — даже если человек в прошлый раз свернул отбор.
  const [expanded, setExpanded] = useFiltersExpanded(problem !== null);
  const formId = useId();
  const problemId = useId();
  /*
   * Кнопка раскрытия — якорь фокуса. Снятый чип исчезает вместе со своей кнопкой,
   * и фокус улетал бы на `body`: следующий Tab начинал бы обход страницы с начала,
   * то есть человек, снявший условие с клавиатуры, терял бы место.
   */
  const toggleRef = useRef<HTMLButtonElement>(null);
  /*
   * Форма доживает выход: без этого сворачивание убрало бы её в том же кадре,
   * и показывать было бы нечего (`useExitHold`).
   */
  const reveal = useExitHold(expanded);

  // Отбор меняется и мимо формы: «сбросить», кнопка «назад», открытая ссылка.
  useEffect(() => {
    setDraft(toDraft(filters));
  }, [filters]);

  const conditions = describeFilters(filters);
  const pending = pendingFields(draft, filters);
  const hasDraft = Object.values(pending).some(Boolean);

  /**
   * Любое изменение отбора отправляет и напечатанное, но ещё не применённое.
   * Иначе флажок, поставленный после набора текста, молча стирал бы этот текст:
   * в адрес он не попал, а форма перечиталась бы из адреса.
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

  function toggle<T extends string>(list: T[], value: T, on: boolean): T[] {
    return on ? [...list, value] : list.filter((item) => item !== value);
  }

  return (
    /*
     * Промежуток между строкой отбора и формой стоит на самой форме (`mt-2`), а не
     * `gap-2` на разделе: промежуток между соседями держится, пока стоит сосед, и
     * свёртывание кончалось бы скачком в восемь пикселей — тем самым рывком, только
     * поменьше. Внутри обёртки он уезжает вместе с местом и доходит до нуля.
     */
    <section className="flex flex-col" aria-label="Отбор задач">
      {/*
       * Свёрнутый вид: одна строка, которая называет весь отбор. Её высота и есть то,
       * что первый экран списка платит за отбор, — всё остальное принадлежит задачам.
       */}
      <div className="flex flex-wrap items-center gap-2 rounded-control border border-line bg-surface px-3 py-2">
        <Button
          ref={toggleRef}
          tone="quiet"
          aria-expanded={expanded}
          aria-controls={formId}
          onClick={() => setExpanded(!expanded)}
        >
          {expanded ? 'Свернуть отбор' : 'Изменить отбор'}
        </Button>

        {/* Список, а не абзац: `aria-label` роль абзаца не принимает, и программа
            чтения с экрана называет число условий вслух — «список из трёх». */}
        {/*
         * Условия занимают всё свободное место и переносятся на вторую строку, когда их
         * много. Ни `overflow: hidden`, ни счётчика «ещё 2»: спрятанное условие — это
         * отфильтрованный список, который принимают за полный.
         */}
        <ul
          className="flex grow basis-48 flex-wrap items-center gap-x-2 gap-y-1 list-none p-0"
          aria-label="Условия отбора"
        >
          {conditions.length === 0 ? (
            <li className="text-meta text-muted">показаны все задачи</li>
          ) : (
            conditions.map((condition) => (
              /*
               * Чип — не кнопка с кнопкой внутри: снятие стоит рядом с текстом условия,
               * а не вложено в другую мишень. Текст условия читается, а не нажимается:
               * раскрывает форму по-прежнему одна кнопка слева.
               *
               * Пилюля, а не прямоугольник, — чтобы условие отбора не путалось с плашкой
               * значения в строке списка (решение Д5).
               */
              <li
                key={condition.id}
                className="inline-flex items-center gap-1 rounded-pill border border-line-strong bg-surface pr-1 pl-2 text-mark text-text leading-[1.7] whitespace-nowrap"
              >
                <span>{condition.label}</span>
                <button
                  type="button"
                  /*
                   * `border-current` рядом с `border-none`: без него у кнопки остаётся цвет
                   * рамки из таблицы браузера (`ButtonBorder` — чёрный днём, белый ночью),
                   * тогда как `border: none` возвращал его к `currentColor`. Ширина нулевая,
                   * и глазом разницы нет, а замер вычисленных стилей её видит.
                   */
                  className="grid place-items-center rounded-pill border-none border-current bg-transparent p-0 leading-none text-muted transition-[background-color] duration-(--motion-fast) ease-fast hover:bg-sunken hover:text-text"
                  aria-label={`Убрать условие: ${condition.label}`}
                  onClick={() => {
                    applyWith(CONDITION_RESET[condition.id]);
                    toggleRef.current?.focus();
                  }}
                >
                  <X className="size-(--ui-mark)" aria-hidden="true" />
                </button>
              </li>
            ))
          )}
        </ul>

        {/*
         * Порядок стоит в строке, видимой всегда: колонка времени показывает активность
         * в деле, и человек обязан видеть, чем объясняется порядок строк, не разворачивая
         * форму. Подпись поля скрыта в `aria-label`, а не написана рядом: слово
         * «Сортировка» занимало 85 px строки, которые нужнее списку условий, — а каждая
         * подпись вроде «сначала живые в деле» говорит за себя и без него.
         */}
        {board ? null : (
          <Select
            className="whitespace-nowrap"
            label="Сортировка"
            value={filters.sort}
            onValueChange={(sort) => applyWith({ sort })}
            options={TASK_SORTS.map((option) => ({ value: option.value, label: option.label }))}
          />
        )}

        {conditions.length === 0 ? null : (
          <Button tone="quiet" onClick={onReset}>
            Сбросить
          </Button>
        )}
      </div>

      {reveal.held ? (
        <Reveal leaving={reveal.leaving} entering={reveal.entering}>
          <form
            id={formId}
            className="mt-2 flex flex-col gap-3 rounded-control border border-line bg-surface px-4 py-3"
            aria-label="Условия отбора задач"
            onSubmit={submit}
          >
            <div className={LINE}>
              {/*
               * Очереди здесь нет и не должно быть: она стала местом в интерфейсе и живёт
               * в боковой панели (UI-38, решение Д25). В форме остались условия, которые
               * действительно отбор.
               */}
              {board ? null : (
                <fieldset className={GROUP}>
                  <legend className={LABEL}>Статус</legend>
                  {TASK_STATUSES.map((status) => (
                    <label key={status} className={CHECK}>
                      <input
                        type="checkbox"
                        checked={filters.status.includes(status)}
                        onChange={(event) =>
                          applyWith({
                            status: toggle(filters.status, status, event.target.checked),
                          })
                        }
                      />
                      <code className={CODE}>{status}</code>
                    </label>
                  ))}
                </fieldset>
              )}

              <fieldset className={GROUP}>
                <legend className={LABEL}>Приоритет</legend>
                {TASK_PRIORITIES.map((priority) => (
                  <label key={priority} className={CHECK}>
                    <input
                      type="checkbox"
                      checked={filters.priority.includes(priority)}
                      onChange={(event) =>
                        applyWith({
                          priority: toggle(filters.priority, priority, event.target.checked),
                        })
                      }
                    />
                    <code className={CODE}>{priority}</code>
                  </label>
                ))}
              </fieldset>
            </div>

            {board ? (
              <p className={NOTE}>На доске показаны все статусы: каждый своим столбцом.</p>
            ) : null}

            <div className={LINE}>
              <DraftField
                label="Исполнитель"
                value={draft.assignee}
                pending={pending.assignee}
                placeholder="имя целиком"
                onChange={(value) => setDraft({ ...draft, assignee: value })}
              />

              <DraftField
                label="Текст"
                value={draft.text}
                pending={pending.text}
                placeholder="в названии или описании"
                onChange={(value) => setDraft({ ...draft, text: value })}
              />

              <label className={CHECK}>
                <input
                  type="checkbox"
                  checked={filters.blocked}
                  onChange={(event) => applyWith({ blocked: event.target.checked })}
                />
                заблокирована
              </label>

              <label className={CHECK}>
                <input
                  type="checkbox"
                  checked={filters.withQuestions}
                  onChange={(event) => applyWith({ withQuestions: event.target.checked })}
                />
                есть открытые вопросы
              </label>

              <label className={CHECK}>
                <input
                  type="checkbox"
                  checked={filters.withRemarks}
                  onChange={(event) => applyWith({ withRemarks: event.target.checked })}
                />
                есть неразобранные замечания
              </label>
            </div>

            <div className={LINE}>
              <DraftField
                label="Запрос на языке бэкенда"
                note="отменяет остальной отбор"
                value={draft.query}
                pending={pending.query}
                placeholder="queue: DEMO and status: open and blocked: false"
                wide
                invalid={problem !== null}
                describedBy={problem === null ? undefined : problemId}
                onChange={(value) => setDraft({ ...draft, query: value })}
              >
                {/* Объяснение отказа наложено на страницу, а не встроено в поток: иначе
                    две сотни пикселей объяснения уводят таблицу вниз ровно тогда, когда
                    человек хочет сравнить её с тем, что было до опечатки. */}
                {problem === null ? null : <QueryProblemHint id={problemId} problem={problem} />}
              </DraftField>

              {/* Кнопка стоит при поле запроса — самом частом черновике — и включается
                  только тогда, когда есть что применять. Флажки и списки применяются
                  мгновенно и её не ждут. */}
              <Button type="submit" disabled={!hasDraft}>
                Применить
              </Button>
            </div>
          </form>
        </Reveal>
      ) : null}
    </section>
  );
}

interface DraftFieldProps {
  label: string;
  /** Постоянная сноска у подписи: она не появляется по событию и потому ничего не двигает. */
  note?: string;
  value: string;
  /** Напечатано, но ещё не применено: поле само говорит, что ждёт «Применить». */
  pending: boolean;
  placeholder: string;
  wide?: boolean;
  invalid?: boolean;
  describedBy?: string;
  onChange: (value: string) => void;
  children?: ReactNode;
}

/**
 * Текстовое поле отбора: применяется по «Применить» или по Enter, а до тех пор
 * говорит о себе, что ещё не применено.
 *
 * Enter работает сам, потому что поле стоит в форме с кнопкой отправки — отдельного
 * обработчика клавиши здесь нет и быть не должно: он разошёлся бы с кнопкой.
 */
function DraftField({
  label,
  note,
  value,
  pending,
  placeholder,
  wide = false,
  invalid = false,
  describedBy,
  onChange,
  children,
}: DraftFieldProps) {
  const inputId = useId();
  const pendingId = useId();
  const describedByAll = [describedBy, pending ? pendingId : undefined].filter(
    (id): id is string => id !== undefined,
  );

  return (
    <div className={`flex flex-col gap-1${wide ? ' grow basis-96' : ''}`}>
      {/* Подпись связана с полем через `htmlFor`, а не обёрткой: внутрь поля запроса
          кладётся объяснение отказа с указателем на символ, а `label` вправе держать
          только строчное содержимое. */}
      {/*
       * Сноска и признак черновика стоят рядом с подписью, а не внутри неё: имя поля
       * для программы чтения с экрана — это текст `label`, и «Запрос на языке бэкенда
       * отменяет остальной отбор, не применено» именем быть не должно. С полем они
       * связаны через `aria-describedby` — как пояснение, а не как имя.
       */}
      <div className="flex items-baseline gap-2">
        <label className={LABEL} htmlFor={inputId}>
          {label}
        </label>
        {note === undefined ? null : <span className={NOTE}>{note}</span>}
        {pending ? (
          <span className="text-label font-semibold text-attention" id={pendingId}>
            не применено, Enter применит
          </span>
        ) : null}
      </div>
      <div className="relative block">
        <input
          id={inputId}
          className={cn(
            'w-full min-w-40 rounded-mark border bg-surface px-2 py-1 text-body text-text',
            pending
              ? // Черновик поля: напечатано, но в адрес ещё не уехало.
                'border-attention-line shadow-[inset_3px_0_0_var(--color-attention-line)]'
              : 'border-line-strong',
          )}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder={placeholder}
          autoComplete="off"
          spellCheck={false}
          aria-invalid={invalid}
          aria-describedby={describedByAll.length === 0 ? undefined : describedByAll.join(' ')}
        />
        {children}
      </div>
    </div>
  );
}

/**
 * Что сказал бэкенд о негодном отборе: фраза по коду, место в строке и допустимое.
 * Позиция называется и словами, и указателем: указатель виден глазами, слова
 * читаются программой чтения с экрана.
 */
function QueryProblemHint({ id, problem }: { id: string; problem: QueryProblem }) {
  return (
    /*
     * Объяснение отказа наложено на страницу, а не встроено в поток формы: встроенное
     * уводило бы таблицу вниз на две сотни пикселей ровно в тот момент, когда человек
     * правит запрос и сверяется с прошлой выдачей.
     */
    <div
      className="absolute top-[calc(100%+var(--spacing))] left-0 z-5 flex min-w-full max-w-160 flex-col gap-2 rounded-mark border border-danger-line bg-danger-soft px-4 py-3 text-body text-danger shadow-raised"
      id={id}
      role="alert"
    >
      <p>
        {problem.message}
        {problem.position === null ? null : ` Ошибка в символе ${problem.position + 1}.`}
      </p>

      {problem.position === null || problem.query === '' ? null : (
        <pre
          className="overflow-x-auto font-mono text-meta leading-[1.2] whitespace-pre"
          aria-hidden="true"
        >
          {`${problem.query}\n${caretLine(problem.query, problem.position)}`}
        </pre>
      )}

      {problem.allowed.length === 0 ? null : <p>Допустимо: {problem.allowed.join(', ')}</p>}

      {/* Таблица под формой продолжает показывать прошлую удачную выдачу; сказать
          об этом надо здесь, у отказа, а не полосой над таблицей, которая её сдвинет. */}
      <p>Показаны строки предыдущего отбора.</p>
    </div>
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
