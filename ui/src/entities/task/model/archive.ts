import { ApiError } from '@/shared/api';
import type { TaskStatus } from '../api/tasks';

/*
 * Архив — закрытые задачи, в делах которых давно ничего не происходит.
 *
 * Правило представления, а не состояние задачи (решение владельца от 11 сентября 2026,
 * UI-97): трекер ничего не архивирует и ничего для этого не хранит, признак следует из
 * `status` и `features.last_entry_at` в момент чтения. Прячет его только интерфейс
 * человека — выдача API по умолчанию прежняя, и агент в `search_tasks` видит всё.
 */

/** Сколько дней тишины в деле делают закрытую задачу архивной. Одно место, не настройка. */
export const ARCHIVE_AFTER_DAYS = 3;

/** Статусы, в которых задача закрыта: в архив уходят из них и только из них. */
export const CLOSED_STATUSES = ['done', 'cancelled'] as const satisfies readonly TaskStatus[];

const DAY_MS = 24 * 60 * 60 * 1000;

/**
 * Мгновение порога: закрытая задача, в деле которой не писали с этого мгновения,
 * в архиве.
 *
 * Абсолютное и в UTC: относительных значений (`3d`) язык запросов не принимает
 * намеренно — такая строка завтра значила бы другое (`../tracker/app/services/search.py`,
 * `_timestamp`). Считают его часы браузера: других у интерфейса нет.
 */
export function archiveThreshold(now: Date): string {
  return new Date(now.getTime() - ARCHIVE_AFTER_DAYS * DAY_MS).toISOString();
}

/**
 * «Не в архиве» на языке запросов бэкенда: задача не закрыта — или в её деле писали
 * после порога.
 *
 * Мгновение в кавычках: двоеточие не входит в слово языка, и без кавычек время
 * разобралось бы на слово и лишнее двоеточие.
 *
 * Пустое `last_entry_at` сравнение не проходит, поэтому закрытая задача без единой
 * записи агента или человека в архиве сразу (UI-97#6). Пустота тишину не прерывает —
 * она и есть тишина: иначе чем меньше в задаче было работы, тем дольше она стояла бы
 * на виду, а отменённые одноразовые задачи копились бы в столбце без конца.
 */
export function outsideArchive(now: Date): string {
  const closed = CLOSED_STATUSES.join(', ');
  return `status: not in ${closed} or last_entry_at: >= "${archiveThreshold(now)}"`;
}

/** Запрос, сложенный с правилом архива, и обратный путь его отказа. */
export interface ArchiveQuery {
  /** Что уходит в параметр `query`. */
  query: string;
  /** Отказ бэкенда в координатах той строки, которую прислал вызывающий. */
  relocate: (error: unknown) => unknown;
}

/** Что стоит перед строкой вызывающего в склейке: позиция отказа сдвинута ровно на него. */
const OPENING = '(';

/**
 * Складывает запрос с правилом архива по «и»: `(запрос) and (правило)`.
 *
 * Склеивает и расклеивает одно место. Отказ разбора, пришедший на склейку, говорит
 * о позиции в склейке, а человек правил свою строку, — поэтому `relocate` возвращает
 * позицию туда, где её ищет человек, и строкой отказа ставит его строку (UI-97#8).
 * Запрос идёт первым: его условия считаются первыми, и лимит числа условий, если его
 * перешагнёт склейка, придётся на правило, а не на середину его строки.
 *
 * Строку, которую нельзя обернуть скобками (`wrappable`), не склеивают вовсе: она
 * уходит одна, без правила. Такую строку бэкенд отвергнет всегда, архив наружу не
 * протечёт, а отказ придёт с его собственной позицией. Склеенная же, она двигала бы
 * позицию за край строки человека — а бывает, что и проходила бы, отдавая архив:
 * лишняя `)` закрывала нашу группу, и правило цеплялось к одному хвосту (UI-97#5).
 *
 * Одну ступень вложенности скобок обёртка у человека забирает: запрос на пределе
 * глубины языка в склейке этот предел перешагнёт. Руками такого не пишут.
 */
export function hideArchive(query: string | null | undefined, now: Date): ArchiveQuery {
  const rule = outsideArchive(now);

  if (query === undefined || query === null || query.trim() === '') {
    return { query: rule, relocate: unchanged };
  }
  if (!wrappable(query)) return { query, relocate: unchanged };

  return {
    query: `${OPENING}${query}) and (${rule})`,
    relocate: (error) => relocated(error, query),
  };
}

/**
 * Можно ли обернуть строку скобками, не изменив ни её смысла, ни её отказа: скобки вне
 * кавычек сходятся, и ни одна кавычка не осталась открытой.
 *
 * Это не разбор языка — клиент его по-прежнему не разбирает. Читается ровно то, что
 * решает, где кончится группа: кавычки обоих видов с `\` внутри, как у лексера бэкенда
 * (`../tracker/app/domain/query_language.py`, `_read_string`), и скобки вне них. Скобка
 * в языке не бывает частью слова или оператора, а каждая `)` грамматики закрывает свою
 * `(`, — поэтому несошедшиеся скобки означают строку, которую бэкенд отвергнет и одну.
 */
export function wrappable(query: string): boolean {
  let depth = 0;
  let quote: string | null = null;

  for (let index = 0; index < query.length; index += 1) {
    const char = query[index];

    if (quote !== null) {
      // Обратная косая черта берёт следующий символ как есть — и кавычку тоже.
      if (char === '\\') index += 1;
      else if (char === quote) quote = null;
      continue;
    }

    if (char === '"' || char === "'") quote = char;
    else if (char === '(') depth += 1;
    else if (char === ')') {
      depth -= 1;
      if (depth < 0) return false;
    }
  }

  return quote === null && depth === 0;
}

function unchanged(error: unknown): unknown {
  return error;
}

/**
 * Отказ склейки → отказ строки человека. Трогается только то, что говорит о месте:
 * код, фраза и допустимые значения у склейки те же, что у строки одной.
 *
 * За строкой человека в склейке стоят наша закрывающая скобка и правило. Позиция там
 * для него — конец его строки: ровно там разбор его одной строки и споткнулся бы.
 */
function relocated(error: unknown, query: string): unknown {
  if (!(error instanceof ApiError)) return error;
  const { position } = error.details;
  if (typeof position !== 'number') return error;

  return new ApiError(error.code, error.message, error.status, {
    ...error.details,
    position: Math.min(Math.max(position - OPENING.length, 0), query.length),
    query,
  });
}
