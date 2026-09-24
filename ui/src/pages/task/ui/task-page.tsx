import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useParams, useSearchParams } from 'react-router';
import { useQuery } from '@tanstack/react-query';
import { cva } from 'class-variance-authority';
import { MessageSquarePlus } from 'lucide-react';
import { EntryBody, EntryIndex, type EntryIndexHandle, type Question } from '@/entities/entry';
import { TaskNav, taskPackageQueryOptions } from '@/entities/task';
import {
  AnswerForm,
  AnswerReceipt,
  useAnswering,
  withHeld,
  type Answering,
} from '@/features/answer-question';
import { RemarkForm } from '@/features/leave-remark';
import { ApiError } from '@/shared/api';
import { Button, Callout, QueryState } from '@/shared/ui';
import { caseHref, readEntryNo } from '@/shared/lib';
import { TaskHeader } from './task-header';
import { TaskLinks } from './task-links';
import { TaskSections } from './task-sections';

/**
 * Шапка навигации и шапка задачи остаются прямыми детьми колонки страницы: липкая
 * навигация обязана липнуть относительно всей страницы, а не внутри своей ячейки
 * раскладки — там ей просто некуда двигаться.
 */
const SCREEN = 'flex max-w-(--ui-page-max) flex-col gap-4';

/**
 * Блоки различаются ролью, а не рамкой (решение Д11).
 *
 * `full` — главное: сводка, вопросы, замечания и задание. У них поля, и текст в них
 * живёт с воздухом. Поля сжаты до трёх шагов: карточка обязана уместить на первом
 * экране сводку, вопросы и начало описи, а поля — то место, которое отдаётся дешевле
 * всего (`CONCEPT.md`, 6).
 *
 * `list` — справочное: опись дела и связи. Это списки, и они идут во всю ширину
 * поверхности, без своих полей: свои поля держит содержимое, иначе строки не
 * доходили бы до краёв. Одинаковая рамка на каждом блоке уравнивала главное и
 * справочное, хотя карточку открывают ради первого.
 *
 * `empty` — рамка на подряд идущий пробег пустых состояний, а не на каждое из
 * них: у задачи без сводки, вопросов и замечаний все три раньше рисовали свою
 * рамку подряд, и три рамки съедали первый экран целиком, ничего на нём не
 * сообщив (UI-132). Заголовок и честное «ничего нет» каждого пустого состояния
 * встают своей строкой внутри этой одной рамки — `renderCardBlocks` ниже решает,
 * какие соседние состояния пустые и сшивает только их. Непустое состояние рядом
 * не трогает: оно остаётся отдельным `full`-блоком на своём месте, и заметность
 * его не падает. Сама честность пустого состояния при этом остаётся: текст на
 * месте, просто не в собственной рамке.
 */
const block = cva('flex rounded-control border border-line bg-surface', {
  variants: {
    kind: {
      full: 'flex-col gap-3 p-3',
      list: 'flex-col gap-0',
      empty: 'flex-col gap-1 px-3 py-2',
    },
  },
  defaultVariants: { kind: 'full' },
});

/**
 * Заголовок блока. У пустого он на шаг мельче — блок стал строкой, и заголовок
 * экрана в ней спорил бы с самим текстом.
 *
 * У блока-списка заголовок несёт поля и линию сам: полей у блока нет, а отделить
 * заголовок от строк списка чем-то надо. Цвет линии назван стороной (`border-b-line`):
 * `border-line` покрасил бы все четыре, и три из них перестали бы быть `currentColor`.
 */
const blockTitle = cva('', {
  variants: {
    kind: {
      full: 'text-screen',
      list: 'border-b border-b-line px-3 pt-3 pb-2 text-screen',
      empty: 'text-body',
    },
  },
  defaultVariants: { kind: 'full' },
});

/** Заголовок списка с действием справа: те же поля и та же линия, что у заголовка. */
const BLOCK_HEAD =
  'flex flex-wrap items-baseline justify-between gap-3 border-b border-b-line px-3 pt-3 pb-2';

/**
 * Прыжки по описи: своя строка под шапкой, тем же левым полем, что у заголовка над
 * ней и у ячеек таблицы под ней (`px-3`, тот же, что в `BLOCK_HEAD` и в `CELL`
 * `entities/entry/ui/entry-index.tsx`) — один источник поля вместо разъехавшихся частных отступов
 * (UI-127). Своей нижней линии нет: линию между шапкой и телом уже держит
 * `BLOCK_HEAD`, а это его продолжение, а не отдельная секция.
 */
const INDEX_NAV = 'flex flex-wrap gap-2 px-3 pt-2';

/**
 * Опись длиннее этого читается прокруткой, и по ней имеет смысл прыгать. Короткая
 * видна целиком, и два действия над ней были бы шумом там, где всё и так на экране.
 */
const LONG_INDEX = 12;

/** Плитка открытого вопроса и разобранного замечания: рамка, заливка, свои поля. */
const NOTICE = 'flex flex-col gap-2 rounded-mark border p-3';

/** Список плиток внутри блока: маркеров у него нет, поля тоже — их держат плитки. */
const NOTICE_LIST = 'flex list-none flex-col gap-3 p-0';

/** Честное «ничего нет»: курсив вместо прочерка — его читают, а не сканируют. */
const EMPTY = 'text-muted italic';

/** Одна строка пустого состояния внутри слитой рамки `empty`: заголовок и текст на одной базовой линии. */
const EMPTY_ROW = 'flex flex-row flex-wrap items-baseline gap-2';

/**
 * Карточка задачи: один запрос пакета преемника на открытие экрана
 * (`docs/FRONTEND.md`, «Карточка задачи одним запросом»).
 *
 * Сводка и открытые вопросы приходят целиком и показываются сразу: ради них человек
 * карточку и открыл. Остальные записи — заголовками в описи, тела по клику.
 */
export function TaskPage() {
  const { key = '' } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const pkg = useQuery(taskPackageQueryOptions(key));

  // До ранних возвратов: хук нельзя позвать условно. Держит вопросы, по которым
  // отправка началась, — они остаются на экране вместе с подтверждением, даже когда
  // перечитанный пакет их уже не содержит.
  const answering = useAnswering<Question>();

  /**
   * Раскрыта ли форма замечания. На уровне страницы, а не внутри блока: от неё
   * зависит, показывать ли блок строкой (пусто и форма свёрнута) или карточкой.
   */
  const [remarkOpen, setRemarkOpen] = useState(false);

  /**
   * Прыжок «В начало описи» живёт в шапке блока, а прокручиваемый узел — внутри
   * `EntryIndex` (UI-126, `scroller`): ручка дотягивается до него, не заводя
   * второго пути прокрутки.
   */
  const indexRef = useRef<EntryIndexHandle>(null);

  const openAt = readEntryNo(searchParams.get('entry'));

  /**
   * Раскрытие записи в описи попадает в адрес — тем же параметром, которым запись
   * называет внешняя ссылка. Раньше клик и ссылка делали одно и то же двумя разными
   * способами: ссылка меняла адрес, клик — нет, и перезагрузка теряла раскрытое.
   *
   * `replace`, а не новая запись истории: раскрытие записи — это не «страница»,
   * и кнопка «назад» после трёх кликов по описи должна вести в список, а не
   * разворачивать их обратно по одному.
   */
  const rememberOpen = useCallback(
    (no: number | null) => {
      setSearchParams(
        (current) => {
          const updated = new URLSearchParams(current);
          if (no === null) updated.delete('entry');
          else updated.set('entry', String(no));
          return updated;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  const { t } = useTranslation('task');
  // Кнопка замечания стоит в липкой навигации, а подпись у неё та же, что у формы:
  // действие одно, и называться двумя фразами оно не должно.
  const { t: brick } = useTranslation('ui');

  if (pkg.error instanceof ApiError && pkg.error.code === 'task_not_found') {
    return (
      <main className={SCREEN}>
        <h1 className="text-title">{t('missingTitle', { key })}</h1>
        <Callout>{t('missingText')}</Callout>
        <Link to="/tasks">{t('backToList')}</Link>
      </main>
    );
  }

  if (pkg.data === undefined) {
    return (
      <main className={SCREEN}>
        <QueryState query={pkg} loading={t('loading', { key })} />
      </main>
    );
  }

  const { task, features, summary, parent, children, links, index, remarks } = pkg.data;
  const questions = withHeld(pkg.data.questions, answering.held, (question) =>
    questionId(task.key, question),
  );

  /*
   * Три блока левой колонки — сводка, вопросы, замечания — решают порознь, пусты ли
   * они, а рисует их `renderCardBlocks`: подряд идущие пустые сшиваются в одну рамку
   * (`block`, kind `empty`, выше), а непустой остаётся своим `full`-блоком на месте.
   */
  const cardBlocks: CardBlock[] = [];

  if (summary == null) {
    cardBlocks.push({
      empty: true,
      key: 'summary',
      id: 'summary',
      title: t('summary'),
      text: t('noSummary'),
    });
  } else {
    cardBlocks.push({
      empty: false,
      key: 'summary',
      node: (
        <section key="summary" className={block()} aria-labelledby="summary">
          <h2 className={blockTitle()} id="summary">
            {t('summary')}
          </h2>
          <EntryBody entry={summary} />
        </section>
      ),
    });
  }

  if (questions.length === 0) {
    cardBlocks.push({
      empty: true,
      key: 'questions',
      id: 'questions',
      title: t('questions'),
      text: t('noQuestions'),
    });
  } else {
    cardBlocks.push({
      empty: false,
      key: 'questions',
      node: (
        <section key="questions" className={block()} aria-labelledby="questions">
          <h2 className={blockTitle()} id="questions">
            {t('questions')}
          </h2>
          <ul className={NOTICE_LIST}>
            {questions.map((question, at) => (
              /* Красным здесь только то, что действительно держит работу, —
                 открытый вопрос. */
              <li key={question.no} className={`${NOTICE} border-danger-line bg-danger-soft`}>
                <p className="font-semibold">
                  {task.key}#{question.no} · {question.title}
                </p>
                <EntryBody entry={question} />
                <QuestionAnswer
                  taskKey={task.key}
                  question={question}
                  at={at}
                  answering={answering}
                  askedFor={openAt === question.no}
                />
              </li>
            ))}
          </ul>
        </section>
      ),
    });
  }

  const remarksEmpty = remarks.length === 0 && !remarkOpen;
  if (remarksEmpty) {
    cardBlocks.push({
      empty: true,
      key: 'remarks',
      id: 'remarks',
      title: t('remarks'),
      text: t('noRemarks'),
    });
  } else {
    cardBlocks.push({
      empty: false,
      key: 'remarks',
      node: (
        <section key="remarks" className={block()} aria-labelledby="remarks">
          <h2 className={blockTitle()} id="remarks">
            {t('remarks')}
          </h2>
          {remarks.length === 0 ? (
            <p className={EMPTY}>{t('noRemarks')}</p>
          ) : (
            <ul className={NOTICE_LIST}>
              {remarks.map((remark) => (
                /*
                 * Замечание выделено тоном внимания, а не опасности: оно правит курс,
                 * но ничего не останавливает (`../docs/CONCEPT.md`, 3.4).
                 */
                <li key={remark.no} className={`${NOTICE} border-attention-line bg-attention-soft`}>
                  <p className="font-semibold">
                    {task.key}#{remark.no} · {remark.title}
                  </p>
                  <EntryBody entry={remark} />
                </li>
              ))}
            </ul>
          )}
          {/*
           * Форма свёрнута, пока её не попросили: поле в пять строк стоит около 180
           * пикселей экрана, и платить за него должен тот, кто пришёл писать. Открыть
           * её можно на задаче в любом статусе, включая закрытую: именно на сделанное
           * человек и смотрит, когда говорит «вышло не то».
           */}
          {remarkOpen ? (
            <RemarkForm taskKey={task.key} onCancel={() => setRemarkOpen(false)} />
          ) : null}
        </section>
      ),
    });
  }

  // Последняя запись всего дела: опись приходит пакетом задачи целиком, поэтому это
  // именно последняя, а не последняя из подгруженных (`docs/FRONTEND.md`).
  const lastEntryNo = index.at(-1)?.no ?? null;
  const showIndexNav = index.length > LONG_INDEX && lastEntryNo !== null;

  return (
    <main className={SCREEN}>
      {/*
       * Единственное, что человек начинает сам, стоит в липкой строке: до неё не надо
       * прокручивать опись в сотню записей. Второй такой кнопки в блоке замечаний нет —
       * заменённый путь удалён, а не оставлен вторым вариантом.
       */}
      <TaskNav
        taskKey={task.key}
        view="card"
        action={
          remarkOpen ? null : (
            // Главное действие строки — акцентом и со знаком, но размером строки: рядом
            // стоит переключатель вида того же `sm`, и они одной высоты (UI-128).
            //
            // На телефоне подпись уходит диктору, на виду остаётся знак — тот же приём,
            // что у переключателя списка (UI-134): со словами строка «назад, вид,
            // действие» в 390 px не помещалась, и действие уезжало второй строкой,
            // переставая стоять вровень с переключателем (UI-144).
            <Button size="sm" onClick={() => setRemarkOpen(true)}>
              <MessageSquarePlus className="size-(--ui-mark)" aria-hidden="true" />
              <span className="max-fold:sr-only">{brick('remark.submit')}</span>
            </Button>
          )
        }
      />
      <TaskHeader task={task} features={features} parent={parent ?? null} />

      {/*
       * Две колонки, каждая своим потоком, и делятся они на точке `card` (80rem).
       * Слева то, ради чего карточку открывают: сводка, вопросы, замечания и опись
       * дела. Справа то, что читают реже: задание и связи. Доли 3:2.
       *
       * Колонки, а не сетка из блоков: сетка связывала их высоты — длинное задание
       * справа растягивало ряд, и опись слева уезжала за первый экран 1440×900,
       * стоило добавить справа четвёртый блок (`e2e/layout.spec.ts`). Колонками этого
       * не случается вовсе: каждая складывается сама по себе.
       *
       * Узкий экран ставит колонки друг за другом, и порядок разметки становится
       * порядком показа. Переставлять его `order` нельзя: Tab и программа чтения
       * с экрана всё равно шли бы по разметке.
       *
       * `card:min-w-0` обязателен обеим: без него длинная строка в колонке растянула
       * бы её шире доли и увела бы страницу в горизонтальную прокрутку.
       */}
      <div className="flex flex-col gap-4 card:flex-row card:items-start">
        <div className="flex flex-col gap-4 card:min-w-0 card:flex-[3_1_0]">
          {/*
           * Сводка, вопросы и замечания стоят до описи, а не после неё: это то, ради
           * чего карточку открывают, и единственный способ, каким человек участвует
           * в работе сам (`../docs/CONCEPT.md`, 3.4). В правой колонке они оказывались
           * за всей описью в порядке чтения — на узком экране на 3527-м пикселе, — то
           * есть дальше всего от человека лежало ровно то, ради чего он сюда приходит.
           * Порядок задаёт разметка, а не `order`: Tab и программа чтения с экрана
           * идут по ней, а не по тому, как блоки расставлены на экране.
           *
           * Форма замечания не привязана к элементу выдачи и переживает перечитывание
           * пакета — в отличие от формы ответа, которая уходит вместе со своим
           * вопросом.
           */}
          {renderCardBlocks(cardBlocks)}

          <section className={block({ kind: 'list' })} aria-labelledby="case">
            <div className={BLOCK_HEAD}>
              {/* Заголовок и число записей — одна группа: число читается частью
                  названия блока, а не отдельной строкой между кнопками и таблицей,
                  как было раньше. */}
              <span className="inline-flex flex-wrap items-baseline gap-3">
                <h2 className="text-screen" id="case">
                  {t('case')}
                </h2>
                {index.length > 0 ? (
                  <span className="text-meta text-muted">
                    {brick('index.count', { count: index.length })}
                  </span>
                ) : null}
              </span>

              {/* Переход в ленту живёт и в липкой навигации сверху: здесь он был на
              1300-м пикселе прокрутки и находился только теми, кто дочитал. */}
              <Link to={caseHref(task.key)}>{t('openCase')}</Link>
            </div>

            {showIndexNav ? (
              /*
               * Два прыжка по описи: к свежей записи и обратно к началу. Свежая
               * раскрывается и читается точечно — своим запросом на свой номер, а не
               * чтением всего дела до неё. Прыгает человек, а не экран: живой поток
               * опись не прокручивает. Левый край — тот же, что у заголовка и у первой
               * колонки таблицы (`INDEX_NAV`), а не голый край блока. Размер `sm` —
               * кнопка в подписи блока по шкале `control-size.ts`.
               */
              <div className={INDEX_NAV}>
                <Button tone="quiet" size="sm" onClick={() => rememberOpen(lastEntryNo)}>
                  {t('index.toLatest')}
                </Button>
                <Button tone="quiet" size="sm" onClick={() => indexRef.current?.scrollToTop()}>
                  {t('index.toTop')}
                </Button>
              </div>
            ) : null}

            <EntryIndex
              ref={indexRef}
              owner={{ kind: 'task', key: task.key }}
              index={index}
              checks={task.checks}
              openAt={openAt}
              onOpenChange={rememberOpen}
            />
          </section>
        </div>

        <div className="flex flex-col gap-4 card:min-w-0 card:flex-[2_1_0]">
          <section className={block()} aria-labelledby="sections">
            <h2 className={blockTitle()} id="sections">
              {t('assignment')}
            </h2>
            {/* Задание показывается целиком и не прячется под сворачивание: это
                договор с агентом, его читают подряд и ищут поиском браузера. */}
            <TaskSections task={task} />
          </section>

          <section className={block({ kind: 'list' })} aria-labelledby="links">
            <h2 className={blockTitle({ kind: 'list' })} id="links">
              {t('links')}
            </h2>
            <TaskLinks parent={parent ?? null} childTasks={children} links={links} />
          </section>
        </div>
      </div>
    </main>
  );
}

/** Непустой блок левой колонки: уже собранная разметка, ключ на месте. */
interface FullCardBlock {
  empty: false;
  key: string;
  node: ReactNode;
}

/** Пустой блок левой колонки: род и честный текст, разметку решает `renderCardBlocks`. */
interface EmptyCardBlock {
  empty: true;
  key: string;
  id: string;
  title: string;
  text: string;
}

type CardBlock = FullCardBlock | EmptyCardBlock;

/**
 * Рисует блоки левой колонки по порядку и сшивает подряд идущие пустые в одну рамку
 * (UI-132): у задачи без сводки, вопросов и замечаний три отдельных «ничего нет» не
 * рисуют трёх рамок, а рамку — одну, со всеми тремя строками внутри. Непустой блок
 * прерывает пробег и остаётся своим `full`-блоком на месте: заметность его не падает.
 */
function renderCardBlocks(blocks: CardBlock[]): ReactNode[] {
  const rendered: ReactNode[] = [];
  let run: EmptyCardBlock[] = [];

  const flushRun = () => {
    if (run.length === 0) return;
    rendered.push(
      <div
        key={`empty-${run.map((item) => item.key).join('-')}`}
        className={block({ kind: 'empty' })}
      >
        {run.map((item) => (
          <div key={item.key} className={EMPTY_ROW}>
            <h2 className={blockTitle({ kind: 'empty' })} id={item.id}>
              {item.title}
            </h2>
            <p className={EMPTY}>{item.text}</p>
          </div>
        ))}
      </div>,
    );
    run = [];
  };

  for (const item of blocks) {
    if (item.empty) run.push(item);
    else {
      flushRun();
      rendered.push(item.node);
    }
  }
  flushRun();

  return rendered;
}

/** Номер записи из адреса. Мусор — то же самое, что его отсутствие. */
/** Тождество вопроса: задача и номер записи — то же, что во входящей. */
function questionId(taskKey: string, question: Question): string {
  return `${taskKey}#${question.no}`;
}

interface QuestionAnswerProps {
  taskKey: string;
  question: Question;
  at: number;
  answering: Answering<Question>;
  /** Адрес называет именно этот вопрос: человека звали отвечать сюда. */
  askedFor: boolean;
}

/**
 * Под вопросом стоит либо кнопка «Ответить», либо форма, либо подтверждение.
 *
 * Форма раскрывается по кнопке, а не стоит раскрытой всегда: поле в пять строк
 * с кнопками — это около 180 пикселей, то есть половина того, чем карточка платит
 * за первый экран. Человек, открывший карточку посмотреть, что происходит, платить
 * за это не должен.
 *
 * Но если адрес называет этот вопрос — человек пришёл по уведомлению или по ссылке
 * из входящей, то есть уже решив отвечать, — форма раскрыта сразу, и лишнего клика
 * между «меня спросили» и «отвечаю» нет.
 */
function QuestionAnswer({ taskKey, question, at, answering, askedFor }: QuestionAnswerProps) {
  const { t: brick } = useTranslation('ui');
  const id = questionId(taskKey, question);
  const answered = answering.answerOf(id);
  const [open, setOpen] = useState(askedFor);

  // Ссылка на другой вопрос той же задачи меняет адрес, не перемонтируя страницу.
  useEffect(() => {
    if (askedFor) setOpen(true);
  }, [askedFor]);

  if (answered !== undefined) {
    return (
      <AnswerReceipt
        taskKey={taskKey}
        questionNo={question.no}
        answered={answered}
        onClose={() => {
          answering.close(id);
          setOpen(false);
        }}
      />
    );
  }

  if (!open && !answering.isHeld(id)) {
    return (
      <div>
        <Button onClick={() => setOpen(true)}>{brick('answer.open')}</Button>
      </div>
    );
  }

  return (
    <AnswerForm
      taskKey={taskKey}
      questionNo={question.no}
      onBegin={() => answering.begin(id, question, at)}
      onFailed={() => answering.fail(id)}
      onAnswered={(result) => answering.complete(id, result)}
      onCancel={() => setOpen(false)}
    />
  );
}
