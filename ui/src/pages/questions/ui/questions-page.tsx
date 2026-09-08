import { useMemo, useState } from 'react';
import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { Link, useSearchParams } from 'react-router';
import {
  questionsQueryOptions,
  remarksQueryOptions,
  type Question,
  type Remark,
} from '@/entities/entry';
import { bootstrapQueryOptions } from '@/entities/session';
import {
  AnswerForm,
  AnswerReceipt,
  useAnswering,
  withHeld,
  type Answering,
} from '@/features/answer-question';
import { Badge, Button, Markdown, QueryState, RelativeTime } from '@/shared/ui';
import { taskRefHref } from '@/shared/lib';

/**
 * Входящая: две половины одной картины — вопросы, которых ждут от человека, и
 * замечания, которых человек ждёт от агентов.
 *
 * Адресата в запрос вопросов не кладём — бэкенд подставляет владельца токена сам
 * (`../tracker/docs/FRONTEND.md`): «моя входящая» не должна знать своего имени. У
 * замечаний адресата нет вовсе, поэтому «мои» здесь означает «мной оставленные», и
 * подпись берётся из первого кадра: страница знает, кто вошёл, а бэкенд по замечанию
 * не догадывается.
 */
export function QuestionsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const bootstrap = useQuery(bootstrapQueryOptions());

  const queue = searchParams.get('queue') ?? '';
  const blocking = searchParams.get('blocking') === 'true';

  const params = useMemo(
    () => ({
      ...(queue === '' ? {} : { queue }),
      ...(blocking ? { blocking: true } : {}),
    }),
    [queue, blocking],
  );

  const questions = useInfiniteQuery(questionsQueryOptions(params));
  const loaded = questions.data?.pages.flatMap((page) => page.items) ?? [];

  const author = bootstrap.data?.participant?.name ?? '';
  const remarks = useInfiniteQuery({
    ...remarksQueryOptions({ ...(queue === '' ? {} : { queue }), author }),
    // Пока неизвестно, кто вошёл, спрашивать нечего: без подписи выдача показала бы
    // чужие замечания под заголовком «мои».
    enabled: author !== '',
  });
  const myRemarks = remarks.data?.pages.flatMap((page) => page.items) ?? [];

  // Вопросы, по которым отправка уже пошла, остаются на экране вместе со своим
  // подтверждением, даже когда выдача их больше не содержит: удачный ответ убирает
  // вопрос из входящей, а человеку надо увидеть, чем всё кончилось.
  const answering = useAnswering<Question>();
  const items = withHeld(loaded, answering.held, questionId);

  /**
   * Условия, действующие на вопросы. Нужны, чтобы отличить «ничего нет» от «ничего
   * не нашлось»: из пустого ответа отобранной выдачи не следует, что агенты вообще
   * ни о чём не спрашивают, — а прежний текст утверждал именно это.
   */
  const questionConditions = [
    ...(queue === '' ? [] : [`очередь ${queue}`]),
    ...(blocking ? ['только блокирующие'] : []),
  ];

  function apply(changes: { queue?: string; blocking?: boolean }) {
    const updated = new URLSearchParams(searchParams);
    if (changes.queue !== undefined) {
      if (changes.queue === '') updated.delete('queue');
      else updated.set('queue', changes.queue);
    }
    if (changes.blocking !== undefined) {
      if (changes.blocking) updated.set('blocking', 'true');
      else updated.delete('blocking');
    }
    setSearchParams(updated, { replace: true });
  }

  return (
    // Предела ширины у экрана нет намеренно: пока она резалась до 64rem, на 1440
    // правая половина пустовала, а два списка шли друг под другом и выглядели
    // продолжением одного (решение Д16). Ширину страницы держит оболочка.
    <main className="flex flex-col gap-4">
      <div>
        <h1 className="text-title">Входящая</h1>
        {/* Что здесь лежит — сказано словами: из названия раздела не видно, что
            половин две, а искать свои замечания человек приходит именно сюда. */}
        <p className="mt-1 text-meta text-muted">
          Вопросы, которых агенты ждут от вас, и ваши замечания, которых ждёте вы.
        </p>
      </div>

      <form
        className="flex flex-wrap items-end gap-4 rounded-control border border-line bg-surface px-4 py-3"
        aria-label="Отбор входящей"
      >
        <label className="flex flex-col gap-1">
          <span className="text-meta text-muted">Очередь</span>
          {/* Фон и цвет названы у поля явно: у `select` есть системная палитра формы,
              и без объявления цвет достаётся ему от браузера, а не от нашей темы
              (`docs/notes/ui.md`, «Кнопка без объявленного фона получает `ButtonFace`»). */}
          <select
            className="rounded-mark border border-line-strong bg-surface px-2 py-1 text-text"
            value={queue}
            onChange={(event) => apply({ queue: event.target.value })}
          >
            <option value="">все очереди</option>
            {(bootstrap.data?.queues ?? []).map((item) => (
              <option key={item.key} value={item.key}>
                {item.key} — {item.title}
              </option>
            ))}
          </select>
        </label>

        {/* Область действия названа рядом с полем: очередь отбирает обе половины,
            а «только блокирующие» стоит внутри вопросов и к замечаниям не относится. */}
        <p className="text-meta text-faint">Очередь отбирает обе половины входящей.</p>
      </form>

      {/*
       * Два списка рядом (решение Д16): на 1440 половина экрана перестаёт пустовать,
       * а вопросы и замечания перестают выглядеть продолжением друг друга. На узком
       * экране сетка складывается в одну колонку в порядке разметки — вопросы первыми.
       *
       * Точка остановки названа решением, а не размером экрана: `wide` — это «входящая
       * встаёт в две колонки». `grid-cols-2` разворачивается в `repeat(2, minmax(0, 1fr))`,
       * то есть половина вправе стать уже своего содержимого: без нижней границы `0`
       * длинное тело вопроса раздвинуло бы колонку и увело страницу вбок.
       *
       * Выравнивание написано свойством, а не утилитой `items-start`: та даёт
       * `align-items: flex-start`, а здесь сетка, и её значение — `start`. Рисуется
       * это одинаково (в сеточном контексте `flex-start` ведёт себя как `start`), но
       * вычисленный стиль расходится, а вместе с ним и слепок, которым доказывают,
       * что вид не изменился.
       */}
      <div className="grid gap-4 [align-items:start] wide:grid-cols-2">
        <section aria-labelledby="questions-section" className="flex flex-col gap-3">
          <h2 className="text-screen" id="questions-section">
            Вопросы ко мне
          </h2>

          {/*
           * Флажок принадлежит вопросам и стоит у них: блокирующих замечаний не бывает,
           * и в общей форме он обещал бы отбор, которого нет. Под заголовком, а не в
           * одной строке с ним: в строке он поднимал заголовок левой половины на два
           * пикселя относительно правой, и колонки переставали начинаться на одной линии.
           */}
          <label className="inline-flex cursor-pointer items-center gap-2">
            <input
              type="checkbox"
              checked={blocking}
              onChange={(event) => apply({ blocking: event.target.checked })}
            />
            только блокирующие
          </label>

          <QueryState
            query={questions}
            loading="Читаем входящую…"
            empty={
              items.length === 0
                ? questionConditions.length === 0
                  ? 'Вопросов без ответа нет: агенты вас не ждут.'
                  : emptyByFilter(questionConditions, () => apply({ queue: '', blocking: false }))
                : undefined
            }
          />

          <ul className="flex list-none flex-col gap-3 p-0">
            {items.map((question, at) => (
              <li key={questionId(question)}>
                <QuestionRow question={question} at={at} answering={answering} />
              </li>
            ))}
          </ul>

          {questions.hasNextPage ? (
            <Button
              onClick={() => void questions.fetchNextPage()}
              disabled={questions.isFetchingNextPage}
            >
              {questions.isFetchingNextPage ? 'Читаем…' : 'Ещё'}
            </Button>
          ) : null}
        </section>

        {/*
         * Вторая половина: что человек сказал агентам и на что ему ещё не ответили.
         * Здесь только чтение — замечание оставляют на карточке задачи, глядя на то,
         * о чём оно.
         */}
        <section aria-labelledby="remarks-section" className="flex flex-col gap-3">
          <h2 className="text-screen" id="remarks-section">
            Мои замечания без разбора
          </h2>

          <QueryState
            query={remarks}
            loading="Читаем замечания…"
            empty={
              myRemarks.length === 0
                ? queue === ''
                  ? 'Неразобранных замечаний нет.'
                  : emptyByFilter([`очередь ${queue}`], () => apply({ queue: '' }))
                : undefined
            }
          />

          <ul className="flex list-none flex-col gap-3 p-0">
            {myRemarks.map((remark) => (
              <li key={`${remark.task_key}#${remark.no}`}>
                <RemarkRow remark={remark} />
              </li>
            ))}
          </ul>

          {remarks.hasNextPage ? (
            <Button
              onClick={() => void remarks.fetchNextPage()}
              disabled={remarks.isFetchingNextPage}
            >
              {remarks.isFetchingNextPage ? 'Читаем…' : 'Ещё'}
            </Button>
          ) : null}
        </section>
      </div>
    </main>
  );
}

/**
 * Пустота по отбору: что именно не нашлось и как снять условия.
 *
 * Отдельно от пустоты без отбора намеренно: «агенты вас не ждут» — вывод обо всей
 * входящей, и делать его по отобранной выдаче нельзя. Условия перечислены поимённо,
 * потому что человек мог забыть про одно из них.
 */
function emptyByFilter(conditions: string[], onReset: () => void) {
  return (
    <>
      По этому отбору ({conditions.join(', ')}) ничего не нашлось.{' '}
      {/* Снятие отбора прямо из объяснения: человек уже читает, почему ничего не
          нашлось. Набрано ссылкой, но осталось кнопкой — оно меняет отбор, а не ведёт
          по адресу; фон назван явно, иначе кнопке достаётся системный. */}
      <button
        type="button"
        className="border-none bg-transparent p-0 text-accent underline"
        onClick={onReset}
      >
        Сбросить отбор
      </button>
    </>
  );
}

/** Замечание во входящей: к какой задаче, когда оставлено и о чём. */
function RemarkRow({ remark }: { remark: Remark }) {
  return (
    // Кромка тоном внимания, а не опасности: замечание ждёт ответа, но ничего не
    // держит. Красное во входящей остаётся за блокирующим вопросом — тем, из-за
    // которого работа действительно стоит.
    <article className="flex flex-col gap-2 rounded-control border border-attention-line bg-surface p-3">
      <header className="flex flex-wrap items-center gap-3 text-meta text-muted">
        {/* Подпись `KEY#N` и адрес собираются одним правилом: ссылка, называющая
            запись, обязана её и открывать (`shared/lib`, `taskRefHref`). */}
        <Link className="font-mono" to={taskRefHref({ key: remark.task_key, entryNo: remark.no })}>
          {remark.task_key}#{remark.no}
        </Link>
        <Badge tone="attention">ждёт разбора</Badge>
        <RelativeTime value={remark.created_at} />
      </header>

      <h3 className="text-screen">{remark.title}</h3>
      <Markdown>{remark.body}</Markdown>
    </article>
  );
}

/** Тождество вопроса на всё приложение: задача и номер записи. */
function questionId(question: Question): string {
  return `${question.task_key}#${question.no}`;
}

interface QuestionRowProps {
  question: Question;
  /** Место в списке: закреплённый вопрос вернётся именно сюда. */
  at: number;
  answering: Answering<Question>;
}

/** Вопрос во входящей: откуда он, о чём и чем на него ответить. */
function QuestionRow({ question, at, answering }: QuestionRowProps) {
  const id = questionId(question);
  const [open, setOpen] = useState(false);
  const answered = answering.answerOf(id);

  const blocking = question.payload.blocking;

  return (
    /*
     * Красной кромки у блокирующего вопроса (решение Д17) здесь нет — и на экране её
     * не было: в модуле правило `.blocking` стояло **выше** `.question`, специфичность
     * у них равная, и позднее правило перебивало кромку целиком. Замерено до перевода
     * на живом контуре: `borderLeftWidth` 1px, `borderLeftColor` `rgb(231, 233, 239)`
     * (`--color-line`) вместо 3px `--color-danger`. Переносится то, что видно, поэтому
     * кромка здесь не воскрешена: это была бы правка вида, а не перевод оформления.
     * Возвращать её — отдельным решением (замер и разбор — `UI-53#5`, `UI-53#6`).
     *
     * Смысл при этом не потерян и сегодня: его несут плашка «блокирующий» и признак
     * в разметке, а цвет не был единственным носителем даже в замысле.
     */
    <article
      className="flex flex-col gap-2 rounded-control border border-line bg-surface p-4"
      // Признак виден разметке, а не только глазу: сквозной тест ищет блокирующий
      // вопрос по нему, а не по цвету кромки и не по тексту плашки.
      data-blocking={blocking ? 'true' : undefined}
      aria-label={blocking ? `Блокирующий вопрос ${id}` : `Вопрос ${id}`}
    >
      <header className="flex flex-wrap items-center gap-3 text-meta text-muted">
        <Link
          className="font-mono"
          to={taskRefHref({ key: question.task_key, entryNo: question.no })}
        >
          {question.task_key}#{question.no}
        </Link>
        {/* Плашка остаётся рядом с признаком: цвет не единственный носитель смысла. */}
        {blocking ? <Badge tone="danger">блокирующий</Badge> : null}
        <RelativeTime value={question.created_at} />
      </header>

      <h2 className="text-screen">{question.title}</h2>

      {/* Тело без обёртки записи: адресат здесь всегда один и тот же — тот, кто смотрит
          входящую, — и повторять «Кому: owner» у каждого вопроса незачем. */}
      <Markdown>{question.body}</Markdown>

      {answered !== undefined ? (
        <AnswerReceipt
          taskKey={question.task_key}
          questionNo={question.no}
          answered={answered}
          onClose={() => {
            answering.close(id);
            setOpen(false);
          }}
        />
      ) : open || answering.isHeld(id) ? (
        <AnswerForm
          taskKey={question.task_key}
          questionNo={question.no}
          onBegin={() => answering.begin(id, question, at)}
          onFailed={() => answering.fail(id)}
          onAnswered={(result) => answering.complete(id, result)}
        />
      ) : (
        <div>
          <Button onClick={() => setOpen(true)}>Ответить</Button>
        </div>
      )}
    </article>
  );
}
