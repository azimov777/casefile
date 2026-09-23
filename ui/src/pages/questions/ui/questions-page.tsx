import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { Link, useSearchParams } from 'react-router';
import {
  AuthorName,
  questionHistoryQueryOptions,
  questionsQueryOptions,
  remarksQueryOptions,
  type Question,
  type QuestionAnswer,
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
import {
  Badge,
  Button,
  Markdown,
  QueryState,
  RelativeTime,
  SegmentedNav,
  SegmentedNavLink,
} from '@/shared/ui';
import { taskRefHref } from '@/shared/lib';

/**
 * Экран вопросов: входящая первым экраном, история вопросов — вторым уровнем.
 *
 * Вид живёт в адресе (`view=history`), как любой отбор: ссылку на историю можно
 * переслать, а «назад» браузера возвращает к входящей. Без параметра — входящая, та
 * же, что была до истории (UI-147): открытые вопросы ко мне и мои замечания. Виды —
 * отдельные компоненты, а не ветки одного: у каждого свои запросы, и входящая не
 * должна читать свою выдачу, пока человек листает историю.
 */
export function QuestionsPage() {
  const [searchParams] = useSearchParams();
  return searchParams.get('view') === 'history' ? <QuestionHistory /> : <Inbox />;
}

/**
 * Входящая: две половины одной картины — вопросы, которых ждут от человека, и
 * замечания, которых человек ждёт от агентов.
 *
 * Адресата в запрос вопросов не кладём — бэкенд подставляет владельца токена сам
 * (`docs/FRONTEND.md`): «моя входящая» не должна знать своего имени. У
 * замечаний адресата нет вовсе, поэтому «мои» здесь означает «мной оставленные», и
 * подпись берётся из первого кадра: страница знает, кто вошёл, а бэкенд по замечанию
 * не догадывается.
 */
function Inbox() {
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
  const { t } = useTranslation('questions');
  const { t: brick } = useTranslation('ui');

  /**
   * Условия, действующие на вопросы. Нужны, чтобы отличить «ничего нет» от «ничего
   * не нашлось»: из пустого ответа отобранной выдачи не следует, что агенты вообще
   * ни о чём не спрашивают, — а прежний текст утверждал именно это.
   */
  const questionConditions = [
    ...(queue === '' ? [] : [t('condition.queue', { queue })]),
    ...(blocking ? [t('condition.blocking')] : []),
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
        {/* Название раздела одно на панель и на заголовок экрана: разъехавшись, они
            назвали бы одно место двумя словами. */}
        <h1 className="text-title">{brick('app.inbox')}</h1>
        {/* Что здесь лежит — сказано словами: из названия раздела не видно, что
            половин две, а искать свои замечания человек приходит именно сюда. */}
        <p className="mt-1 text-meta text-muted">{t('intro')}</p>
      </div>

      <QuestionsViewSwitch view="inbox" />

      <form
        className="flex flex-wrap items-end gap-4 rounded-control border border-line bg-surface px-4 py-3"
        aria-label={t('filterLabel')}
      >
        <label className="flex flex-col gap-1">
          <span className="text-meta text-muted">{t('queue')}</span>
          {/* Фон и цвет названы у поля явно: у `select` есть системная палитра формы,
              и без объявления цвет достаётся ему от браузера, а не от нашей темы
              (`docs/notes/ui.md`, «Кнопка без объявленного фона получает `ButtonFace`»). */}
          <select
            className="rounded-mark border border-line-strong bg-surface px-2 py-1 text-text"
            value={queue}
            onChange={(event) => apply({ queue: event.target.value })}
          >
            <option value="">{t('allQueues')}</option>
            {(bootstrap.data?.queues ?? []).map((item) => (
              <option key={item.key} value={item.key}>
                {item.key} — {item.title}
              </option>
            ))}
          </select>
        </label>

        {/* Область действия названа рядом с полем: очередь отбирает обе половины,
            а «только блокирующие» стоит внутри вопросов и к замечаниям не относится. */}
        <p className="text-meta text-faint">{t('queueNote')}</p>
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
            {t('questionsTitle')}
          </h2>

          {/*
           * Флажок принадлежит вопросам и стоит у них: блокирующих замечаний не бывает,
           * и в общей форме он обещал бы отбор, которого нет. Под заголовком, а не в
           * одной строке с ним: в строке он поднимал заголовок левой половины на два
           * пикселя относительно правой, и колонки переставали начинаться на одной линии.
           */}
          {/* Минимум высоты только на телефоне (`max-fold:`): подпись кликабельна,
              но и вся строка label на 390 px не дотягивала до 24px (UI-154). */}
          <label className="inline-flex cursor-pointer items-center gap-2 max-fold:min-h-(--ui-tap)">
            <input
              type="checkbox"
              checked={blocking}
              onChange={(event) => apply({ blocking: event.target.checked })}
            />
            {t('blockingOnly')}
          </label>

          <QueryState
            query={questions}
            loading={t('loadingQuestions')}
            empty={
              items.length === 0
                ? questionConditions.length === 0
                  ? t('noQuestions')
                  : emptyByFilter(
                      questionConditions,
                      () => apply({ queue: '', blocking: false }),
                      t,
                    )
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
              {questions.isFetchingNextPage ? t('loadingMore') : t('more')}
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
            {t('remarksTitle')}
          </h2>

          <QueryState
            query={remarks}
            loading={t('loadingRemarks')}
            empty={
              myRemarks.length === 0
                ? queue === ''
                  ? t('noRemarks')
                  : emptyByFilter([t('condition.queue', { queue })], () => apply({ queue: '' }), t)
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
              {remarks.isFetchingNextPage ? t('loadingMore') : t('more')}
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
function emptyByFilter(conditions: string[], onReset: () => void, t: TFunction<'questions'>) {
  return (
    <>
      {t('emptyByFilter', { conditions: conditions.join(', ') })}{' '}
      {/* Снятие отбора прямо из объяснения: человек уже читает, почему ничего не
          нашлось. Набрано ссылкой, но осталось кнопкой — оно меняет отбор, а не ведёт
          по адресу; фон назван явно, иначе кнопке достаётся системный. */}
      <button
        type="button"
        className="border-none bg-transparent p-0 text-accent underline"
        onClick={onReset}
      >
        {t('resetFilter')}
      </button>
    </>
  );
}

/** Замечание во входящей: к какой задаче, когда оставлено и о чём. */
function RemarkRow({ remark }: { remark: Remark }) {
  const { t } = useTranslation('questions');

  return (
    // Кромка тоном внимания, а не опасности: замечание ждёт ответа, но ничего не
    // держит. Красное во входящей остаётся за блокирующим вопросом — тем, из-за
    // которого работа действительно стоит.
    <article className="flex flex-col gap-2 rounded-control border border-attention-line bg-surface p-3">
      <header className="flex flex-wrap items-center gap-3 text-meta text-muted">
        {/* Подпись `KEY#N` и адрес собираются одним правилом: ссылка, называющая
            запись, обязана её и открывать (`shared/lib`, `taskRefHref`). `whitespace-nowrap`
            держит ключ целым на переносе шапки — `flex-wrap` рядом с ним переносит
            саму подпись как один блок, а не ломает её посередине (UI-151). */}
        <Link
          className="font-mono whitespace-nowrap"
          to={taskRefHref({ key: remark.task_key, entryNo: remark.no })}
        >
          {remark.task_key}#{remark.no}
        </Link>
        <Badge tone="attention">{t('awaitingResolution')}</Badge>
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

/** Карточка вопроса: у блокирующего и обычного она одна и та же, кроме левой кромки. */
const QUESTION_CARD = 'flex flex-col gap-2 rounded-control border border-line bg-surface p-4';

/**
 * Кромка блокирующего вопроса (решение Д17): 3 px тоном опасности вместо линии слева.
 *
 * Дописывается стороной к общей рамке, а не заменяет её: сокращение `border` задаёт
 * границу целиком, и сторона живёт только пока её правило стоит в собранном CSS **после**
 * сокращения. В удалённом модуле экрана было наоборот — `.blocking` стоял выше `.question`,
 * специфичность у обоих равная, и кромка не рисовалась никогда (замер `UI-53#5`:
 * `borderLeftWidth` 1px, `borderLeftColor` `rgb(231, 233, 239)`). У утилит порядок задаёт
 * не атрибут разметки, а Tailwind, и `border-left-*` он выкладывает после сокращения,
 * поэтому сторона побеждает. Держится это замером, а не чтением: проигравшее в каскаде
 * правило молчит — ни сборка, ни типы, ни поиск класса о нём не скажут
 * (`e2e/questions.spec.ts`, «блокирующий вопрос отмечен красной кромкой»).
 *
 * Цвет здесь не единственный носитель смысла и не вправе им стать: рядом с кромкой
 * стоят плашка «блокирующий» и признак `data-blocking`, потому что цвет не читается ни
 * диктором, ни глазом, который его не различает.
 */
const BLOCKING_EDGE = 'border-l-3 border-l-danger';

/** Вопрос во входящей: откуда он, о чём и чем на него ответить. */
function QuestionRow({ question, at, answering }: QuestionRowProps) {
  const id = questionId(question);
  const [open, setOpen] = useState(false);
  const answered = answering.answerOf(id);
  const { t } = useTranslation('questions');
  const { t: brick } = useTranslation('ui');

  const blocking = question.payload.blocking;

  return (
    <article
      className={blocking ? `${QUESTION_CARD} ${BLOCKING_EDGE}` : QUESTION_CARD}
      // Признак виден разметке, а не только глазу: сквозной тест ищет блокирующий
      // вопрос по нему, а не по цвету кромки и не по тексту плашки.
      data-blocking={blocking ? 'true' : undefined}
      aria-label={
        blocking
          ? t('blockingQuestionLabel', { reference: id })
          : t('questionLabel', { reference: id })
      }
    >
      <header className="flex flex-wrap items-center gap-3 text-meta text-muted">
        <Link
          className="font-mono whitespace-nowrap"
          to={taskRefHref({ key: question.task_key, entryNo: question.no })}
        >
          {question.task_key}#{question.no}
        </Link>
        {/* Плашка остаётся рядом с признаком: цвет не единственный носитель смысла. */}
        {blocking ? <Badge tone="danger">{brick('entry.blocking')}</Badge> : null}
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
          onCancel={() => setOpen(false)}
        />
      ) : (
        <div>
          <Button onClick={() => setOpen(true)}>{brick('answer.open')}</Button>
        </div>
      )}
    </article>
  );
}

/** Вид экрана вопросов: входящая или история. */
type QuestionsView = 'inbox' | 'history';

const VIEWS: QuestionsView[] = ['inbox', 'history'];

/**
 * Адрес вида поверх текущего отбора. Очередь переезжает между видами — человек
 * смотрит одну и ту же очередь двумя способами, — а условия, которых у другого вида
 * нет, снимаются: «только блокирующие» принадлежит входящей, «кому угодно» — истории,
 * и молча унесённые в чужой вид, они вернулись бы при обратном переходе как отбор,
 * которого человек не видел.
 */
function viewSearch(params: URLSearchParams, view: QuestionsView): string {
  const next = new URLSearchParams(params);
  if (view === 'history') {
    next.set('view', 'history');
    next.delete('blocking');
  } else {
    next.delete('view');
    next.delete('to');
  }
  const query = next.toString();
  return query === '' ? '' : `?${query}`;
}

/**
 * Переключатель «входящая / история»: ссылки, а не радиогруппа — вид живёт в адресе,
 * и его смена это переход (`src/shared/ui/segmented-nav.tsx`). Входящая стоит первой и
 * остаётся видом по умолчанию: история — второй уровень, за которым приходят реже.
 */
function QuestionsViewSwitch({ view }: { view: QuestionsView }) {
  const [searchParams] = useSearchParams();
  const { t } = useTranslation('questions');

  return (
    <SegmentedNav label={t('view.label')} className="self-start">
      {VIEWS.map((option) => (
        <SegmentedNavLink
          key={option}
          to={{ search: viewSearch(searchParams, option) }}
          // Оба вида — одна страница `/questions`, поэтому `true`, а не `page`.
          current={option === view && 'true'}
        >
          {t(`view.${option}`)}
        </SegmentedNavLink>
      ))}
    </SegmentedNav>
  );
}

/**
 * История вопросов: все вопросы с ответами, от свежих к старым (UI-147).
 *
 * Ответы и порядок отдаёт бэкенд одной выдачей (`order=newest`, `answers` у строки,
 * TRK-120): собирать ответы из дел по задаче — запрос на строку, а переворачивать
 * страницу на клиенте — ставить вторую страницу выше первой. Адресат по умолчанию —
 * тот, кто смотрит; флажок снимает это условие (`to=anyone` в адресе,
 * `any_addressee` в запросе).
 *
 * Отвечать отсюда нельзя намеренно: это не расширение роли человека, а просмотр.
 * Открытый вопрос виден и здесь, но форма ответа у него — во входящей.
 */
function QuestionHistory() {
  const [searchParams, setSearchParams] = useSearchParams();
  const bootstrap = useQuery(bootstrapQueryOptions());
  const { t } = useTranslation('questions');
  const { t: brick } = useTranslation('ui');

  const queue = searchParams.get('queue') ?? '';
  const anyone = searchParams.get('to') === 'anyone';

  const params = useMemo(
    () => ({
      ...(queue === '' ? {} : { queue }),
      ...(anyone ? { any_addressee: true } : {}),
    }),
    [queue, anyone],
  );
  const history = useInfiniteQuery(questionHistoryQueryOptions(params));
  const items = history.data?.pages.flatMap((page) => page.items) ?? [];

  function apply(changes: { queue?: string; anyone?: boolean }) {
    const updated = new URLSearchParams(searchParams);
    if (changes.queue !== undefined) {
      if (changes.queue === '') updated.delete('queue');
      else updated.set('queue', changes.queue);
    }
    if (changes.anyone !== undefined) {
      if (changes.anyone) updated.set('to', 'anyone');
      else updated.delete('to');
    }
    setSearchParams(updated, { replace: true });
  }

  return (
    <main className="flex flex-col gap-4">
      <div>
        <h1 className="text-title">{brick('app.inbox')}</h1>
        <p className="mt-1 text-meta text-muted">{t('historyIntro')}</p>
      </div>

      <QuestionsViewSwitch view="history" />

      <form
        className="flex flex-wrap items-end gap-4 rounded-control border border-line bg-surface px-4 py-3"
        aria-label={t('historyFilterLabel')}
      >
        <label className="flex flex-col gap-1">
          <span className="text-meta text-muted">{t('queue')}</span>
          {/* Фон и цвет названы явно по той же причине, что и во входящей. */}
          <select
            className="rounded-mark border border-line-strong bg-surface px-2 py-1 text-text"
            value={queue}
            onChange={(event) => apply({ queue: event.target.value })}
          >
            <option value="">{t('allQueues')}</option>
            {(bootstrap.data?.queues ?? []).map((item) => (
              <option key={item.key} value={item.key}>
                {item.key} — {item.title}
              </option>
            ))}
          </select>
        </label>

        <label className="inline-flex cursor-pointer items-center gap-2">
          <input
            type="checkbox"
            checked={!anyone}
            onChange={(event) => apply({ anyone: !event.target.checked })}
          />
          {t('onlyMine')}
        </label>
      </form>

      {/* Заголовок раздела нужен не глазу, а уровням: строки истории — `h3`, и без
          `h2` между ними и `h1` дерево заголовков пропускало бы уровень (`axe`). */}
      <section aria-labelledby="history-section" className="flex flex-col gap-3">
        <h2 className="text-screen" id="history-section">
          {t('historyTitle')}
        </h2>

        <QueryState
          query={history}
          loading={t('loadingHistory')}
          empty={
            items.length === 0
              ? queue === ''
                ? anyone
                  ? t('noHistoryAnyone')
                  : t('noHistory')
                : emptyByFilter([t('condition.queue', { queue })], () => apply({ queue: '' }), t)
              : undefined
          }
        />

        <ul className="flex list-none flex-col gap-3 p-0">
          {items.map((question) => (
            <li key={questionId(question)}>
              <HistoryRow question={question} />
            </li>
          ))}
        </ul>

        {history.hasNextPage ? (
          <Button
            onClick={() => void history.fetchNextPage()}
            disabled={history.isFetchingNextPage}
          >
            {history.isFetchingNextPage ? t('loadingMore') : t('more')}
          </Button>
        ) : null}
      </section>
    </main>
  );
}

/**
 * Вопрос в истории: откуда, кто спросил и кого, о чём — и ответы под ним.
 *
 * Открыт вопрос или отвечен, говорит `answers` из выдачи: пустой список бэкенд
 * называет открытым вопросом (`docs/FRONTEND.md`, «История вопросов»), и клиент здесь
 * ничего не считает сам. Кромка и плашка «блокирующий» — только у открытого: у
 * отвеченного вопроса работа уже не стоит, и красное соврало бы о положении дел.
 */
function HistoryRow({ question }: { question: Question }) {
  const { t } = useTranslation('questions');
  const { t: brick } = useTranslation('ui');
  const reference = questionId(question);
  // `answers` в схеме необязателен только по форме: у поля есть значение по
  // умолчанию, и генератор типов делает его `?`. Выдача несёт его всегда.
  const answers = question.answers ?? [];
  const open = answers.length === 0;
  const blocking = open && question.payload.blocking;

  return (
    <article
      className={blocking ? `${QUESTION_CARD} ${BLOCKING_EDGE}` : QUESTION_CARD}
      data-answered={open ? 'false' : 'true'}
      data-blocking={blocking ? 'true' : undefined}
      aria-label={t('questionLabel', { reference })}
    >
      <header className="flex flex-wrap items-center gap-3 text-meta text-muted">
        <Link
          className="font-mono"
          to={taskRefHref({ key: question.task_key, entryNo: question.no })}
        >
          {reference}
        </Link>
        {open ? (
          <Badge tone="attention">{t('awaitingAnswer')}</Badge>
        ) : (
          <Badge tone="positive">{t('answered')}</Badge>
        )}
        {blocking ? <Badge tone="danger">{brick('entry.blocking')}</Badge> : null}
        <AuthorName author={question.author} />
        <RelativeTime value={question.created_at} />
      </header>

      <h3 className="text-screen">{question.title}</h3>
      {/* Адресат назван: в истории вопрос бывает задан не мне — флажок снимается. */}
      <p className="text-meta text-muted">
        {t('addressees', { names: question.payload.addressees.join(', ') })}
      </p>
      <Markdown>{question.body}</Markdown>

      {open ? (
        <p className="text-muted italic">{t('noAnswerYet')}</p>
      ) : (
        // Ответы вложены в вопрос тем же приёмом, что и в деле: сдвиг и полоса слева.
        <ul
          className="ml-4 flex list-none flex-col gap-3 border-l-2 border-l-line-strong p-0 pl-3"
          aria-label={t('answersLabel', { reference })}
        >
          {answers.map((answer) => (
            <li key={answer.no}>
              <HistoryAnswer answer={answer} />
            </li>
          ))}
        </ul>
      )}
    </article>
  );
}

/** Ответ под вопросом: ссылка `KEY#N` ведёт к самой записи ответа в деле. */
function HistoryAnswer({ answer }: { answer: QuestionAnswer }) {
  const { t } = useTranslation('questions');
  const reference = `${answer.task_key}#${answer.no}`;

  return (
    <article className="flex flex-col gap-1" aria-label={t('answerLabel', { reference })}>
      <header className="flex flex-wrap items-center gap-3 text-meta text-muted">
        <Link className="font-mono" to={taskRefHref({ key: answer.task_key, entryNo: answer.no })}>
          {reference}
        </Link>
        <AuthorName author={answer.author} />
        <RelativeTime value={answer.created_at} />
      </header>
      <Markdown>{answer.body}</Markdown>
    </article>
  );
}
