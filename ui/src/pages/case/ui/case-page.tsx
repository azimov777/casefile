import { useEffect, useMemo } from 'react';
import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { Link, useParams, useSearchParams } from 'react-router';
import {
  ENTRY_PAGE_SIZE,
  ENTRY_TYPES,
  EntryCard,
  caseFeedQueryOptions,
  type Entry,
  type EntryType,
} from '@/entities/entry';
import { TaskNav, taskPackageQueryOptions } from '@/entities/task';
import { ApiError } from '@/shared/api';
import { Button, Callout, QueryState } from '@/shared/ui';
import { readEntryNo } from '@/shared/lib';
import { CaseFilters } from './case-filters';
import styles from './case-page.module.css';

/**
 * Сколько записей показать до той, за которой человек пришёл по ссылке.
 *
 * Ссылка `DEMO-4#137` ведёт к одной записи, но читают её вместе с соседями: решение
 * понятно рядом с попыткой, которая его вызвала. Пять — это примерно экран контекста
 * и один запрос, а не листание всего дела до сто тридцать седьмой записи.
 */
const CONTEXT_BEFORE = 5;

/**
 * Дело лентой: все записи по порядку, каждая нарисована по своему типу.
 *
 * Страницами по курсору бэкенда: дело растёт, и «прочитать всё одним запросом» однажды
 * перестанет помещаться в ответ.
 */
export function CasePage() {
  const { key = '' } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();

  const types = useMemo(() => readTypes(searchParams.getAll('type')), [searchParams]);

  /**
   * С какой записи читать дело. `null` — с начала, число — «всё, что после неё».
   *
   * Окно, а не листание: запись из конца стосорокастраничного дела иначе стоила бы
   * пяти запросов и всех тел по дороге. Живёт в адресе, как и остальное состояние
   * экрана: ссылка на хвост дела пересылается и переживает перезагрузку.
   */
  const from = readEntryNo(searchParams.get('from'));

  const params = useMemo(
    () => ({
      ...(types.length > 0 ? { types } : {}),
      ...(from === null ? {} : { after_no: from }),
    }),
    [types, from],
  );

  const feed = useInfiniteQuery(caseFeedQueryOptions(key, params));
  // Проверки нужны вердиктам: их номера в записи есть, а текст живёт в задаче.
  // Оттуда же приходит полная опись — по ней видно, какая запись в деле последняя.
  const task = useQuery(taskPackageQueryOptions(key));

  const entries = feed.data?.pages.flatMap((page) => page.items) ?? [];
  const replies = groupReplies(entries);

  const index = task.data?.index ?? [];
  /** Последняя запись всего дела, а не последняя из показанных: их легко перепутать. */
  const lastNo = index.at(-1)?.no ?? null;

  /**
   * Запись, названная в адресе. Параметр `entry`, а не якорь `#N`: то же действие
   * человека — «покажи запись N» — называется в адресе одинаково и здесь, и в описи
   * карточки. Якорь вдобавок обрабатывал бы браузер сам, а нам нужно ещё довести
   * до записи саму ленту.
   */
  const wanted = readEntryNo(searchParams.get('entry'));
  const found = entries.some((entry) => entry.no === wanted);
  const inIndex = wanted !== null && index.some((heading) => heading.no === wanted);

  /**
   * Названная запись приезжает окном, а не листанием.
   *
   * Раньше лента дочитывала страницу за страницей, пока запись не найдётся: человек,
   * пришедший по ссылке на запись №137, ждал шесть запросов и получал все тела по
   * дороге. Теперь окно ставится сразу — по описи известно, что такая запись есть.
   */
  const windowStart = wanted === null ? 0 : Math.max(0, wanted - CONTEXT_BEFORE);
  const fetching = feed.isFetching;
  useEffect(() => {
    if (wanted === null || found || !inIndex) return;
    // Пока лента едет, судить не о чем: показанное — прошлое окно, и запись, которая
    // уже в пути, выглядела бы отсюда потерянной. Без этого «к свежей записи» ставило
    // своё окно, а эффект тут же перебивал его своим — и запросов выходило два.
    if (fetching) return;
    if ((from ?? 0) === windowStart) return;
    setSearchParams(
      (previous) => {
        const updated = new URLSearchParams(previous);
        if (windowStart === 0) updated.delete('from');
        else updated.set('from', String(windowStart));
        return updated;
      },
      // Заменой, а не новой записью истории: окно подобрано за человека, и «назад»
      // должно уводить туда, откуда он пришёл, а не в предыдущее окно той же ленты.
      { replace: true },
    );
  }, [wanted, found, inIndex, fetching, from, windowStart, setSearchParams]);

  // Прокрутка повторяется, когда записи наконец пришли: до этого прокручивать не к чему.
  useEffect(() => {
    if (wanted === null || !found) return;
    document.getElementById(`entry-${wanted}`)?.scrollIntoView?.({ block: 'center' });
  }, [wanted, found]);

  /**
   * Запись показать не удалось, и человеку надо сказать почему. Причин ровно две:
   * она не попала в отбор по типу — или её в деле нет вовсе, и это видно по описи.
   * Пустого экрана без объяснения здесь не бывает.
   */
  const missing = wanted !== null && !found && !feed.isFetching && task.data !== undefined;

  /** «К свежей записи»: окно на хвост дела и метка на последней записи. */
  function goToLatest() {
    if (lastNo === null) return;
    const updated = new URLSearchParams(searchParams);
    updated.set('entry', String(lastNo));
    // Хвост целиком, а не одна запись: свежую читают вместе с тем, что к ней привело.
    if (lastNo > ENTRY_PAGE_SIZE) updated.set('from', String(lastNo - ENTRY_PAGE_SIZE));
    else updated.delete('from');
    setSearchParams(updated);
  }

  /** Возврат к началу дела: окно снимается, метка записи вместе с ним. */
  function readFromStart() {
    const updated = new URLSearchParams(searchParams);
    updated.delete('from');
    updated.delete('entry');
    setSearchParams(updated);
  }

  if (task.error instanceof ApiError && task.error.code === 'task_not_found') {
    return (
      <main className={styles.screen}>
        <h1 className={styles.heading}>Дела {key} нет</h1>
        <Callout>Задачи с таким ключом нет, а значит нет и дела.</Callout>
        <Link to="/tasks">Вернуться к списку задач</Link>
      </main>
    );
  }

  return (
    <main className={styles.screen}>
      <TaskNav taskKey={key} view="case" />

      <div className={styles.top}>
        <h1 className={styles.heading}>Дело {key}</h1>
        {/*
         * Переход к свежему — действие человека, а не поведение экрана: живой поток
         * ленту не прокручивает и никогда не прокрутит (UI-13). Кнопка стоит у
         * заголовка, потому что за свежим сюда и приходят.
         */}
        {lastNo === null ? null : (
          <Button tone="quiet" onClick={goToLatest}>
            К свежей записи
          </Button>
        )}
      </div>

      <CaseFilters
        selected={types}
        onChange={(next) => {
          const updated = new URLSearchParams(searchParams);
          updated.delete('type');
          for (const type of next) updated.append('type', type);
          setSearchParams(updated, { replace: true });
        }}
      />

      {/* Окно названо вслух: человек обязан видеть, что перед ним не всё дело. */}
      {from === null ? null : (
        <Callout>
          Показаны записи после {key}#{from}.{' '}
          <button type="button" className={styles.reset} onClick={readFromStart}>
            Читать дело сначала
          </button>
        </Callout>
      )}

      {missing ? (
        <Callout tone={types.length > 0 ? 'neutral' : 'danger'}>
          {types.length > 0 ? (
            <>
              Записи {key}#{wanted} не видно: она не попадает в отбор по типу.{' '}
              <button
                type="button"
                className={styles.reset}
                onClick={() => {
                  const updated = new URLSearchParams(searchParams);
                  updated.delete('type');
                  setSearchParams(updated, { replace: true });
                }}
              >
                Показать все типы
              </button>
            </>
          ) : (
            <>
              Записи {key}#{wanted} в деле нет: возможно, номер набран с опечаткой или ссылка ведёт
              в другую задачу.
            </>
          )}
        </Callout>
      ) : null}

      <QueryState
        query={feed}
        loading="Читаем дело…"
        empty={entries.length === 0 ? 'По этим типам записей в деле нет.' : undefined}
      />

      <div className={styles.feed}>
        {entries.map((entry) => {
          // Отклик живёт под тем, на что отвечает: ответ под вопросом, резолюция под
          // замечанием. Отдельной записью он показывается только тогда, когда его
          // записи рядом нет: отбор по типу или окно, начавшееся после неё.
          const answersTo = repliesTo(entry);
          if (answersTo !== null && entries.some((other) => other.no === answersTo)) {
            return null;
          }

          return (
            <EntryCard
              key={entry.no}
              entry={entry}
              checks={task.data?.task.checks ?? []}
              highlighted={wanted === entry.no}
            >
              {entry.type === 'question' || entry.type === 'remark' ? (
                <RepliesUnder
                  replies={replies.get(entry.no) ?? []}
                  waiting={entry.type === 'question' ? 'Ответа пока нет.' : 'Разбора пока нет.'}
                  highlighted={wanted}
                />
              ) : null}
            </EntryCard>
          );
        })}
      </div>

      <div className={styles.paging}>
        {feed.hasNextPage ? (
          <Button onClick={() => void feed.fetchNextPage()} disabled={feed.isFetchingNextPage}>
            {feed.isFetchingNextPage ? 'Читаем…' : 'Ещё'}
          </Button>
        ) : entries.length === 0 ? null : (
          <span className={styles.end}>
            {from === null
              ? `Это всё дело: записей ${entries.length}.`
              : `Это конец дела: показано записей ${entries.length}.`}
          </span>
        )}
        {from === null ? null : (
          <Button tone="quiet" onClick={readFromStart}>
            Читать дело сначала
          </Button>
        )}
      </div>
    </main>
  );
}

/**
 * Отклики под записью, на которую отвечают: тот же вид записи, но вложенный.
 *
 * Помечается именно названный отклик, а не запись целиком: ссылка вида `DEMO-4#9`
 * ведёт к ответу, а показан он здесь — внутри своего вопроса, и человек должен
 * увидеть, что нашёл именно то, за чем шёл.
 *
 * Ответ и резолюция показываются одинаково намеренно: для читателя это одно и то же
 * событие — «на это ответили», — и два разных вида различали бы то, что различать
 * не нужно. Разными остаются слова ожидания: вопрос ждёт ответа, замечание — разбора.
 */
function RepliesUnder({
  replies,
  waiting,
  highlighted,
}: {
  replies: Entry[];
  waiting: string;
  highlighted: number | null;
}) {
  if (replies.length === 0) {
    return <p className={styles.waiting}>{waiting}</p>;
  }

  return (
    <div className={styles.answers}>
      {replies.map((reply) => (
        <EntryCard
          key={reply.no}
          entry={reply}
          checks={[]}
          highlighted={highlighted === reply.no}
        />
      ))}
    </div>
  );
}

/**
 * Номер записи, под которой стоит отклик, или `null`, если запись самостоятельна.
 *
 * Одно место на обе пары контракта: `answer` → `question_no`, `resolution` →
 * `remark_no`. Третья пара, если она появится, добавляется сюда — и лента подхватит
 * её и в группировке, и в скрытии дубля.
 */
function repliesTo(entry: Entry): number | null {
  if (entry.type === 'answer') return entry.payload.question_no;
  if (entry.type === 'resolution') return entry.payload.remark_no;
  return null;
}

/** Отклики по номеру записи, на которую отвечают. */
function groupReplies(entries: Entry[]): Map<number, Entry[]> {
  const byEntry = new Map<number, Entry[]>();
  for (const entry of entries) {
    const no = repliesTo(entry);
    if (no === null) continue;
    byEntry.set(no, [...(byEntry.get(no) ?? []), entry]);
  }
  return byEntry;
}

/** Типы из адреса: чужое значение отбрасывается, как и в отборе задач. */
function readTypes(values: string[]): EntryType[] {
  return values.filter((value): value is EntryType => (ENTRY_TYPES as string[]).includes(value));
}
