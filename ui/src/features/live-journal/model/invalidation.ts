import type { QueryKey } from '@tanstack/react-query';
import { areaKeys } from '@/entities/area';
import { discussionKeys } from '@/entities/discussion';
import { questionKeys } from '@/entities/entry';
import { projectKeys } from '@/entities/project';
import { splitAreaAddress } from '@/shared/lib';
import { sessionKeys } from '@/entities/session';
import { taskKeys } from '@/entities/task';
import type { JournalFrame } from './frames';

/**
 * Что устарело от записи — и когда это можно перечитать.
 *
 * Границы проходят не по «важности», а по тому, чего стоит человеку движение на
 * экране, который он в этот момент читает.
 *
 * - Карточка открытой задачи, входящая и счётчик вопросов дополняются сверху и
 *   в сторону: прокрутка от них не сбивается, а ждёт человек как раз их.
 * - Доска пересобирает состав столбцов — и ровно за этим на неё и смотрят: карточка,
 *   переехавшая из `in_progress` в `done`, отвечает на вопрос, ради которого доску
 *   открыли. Перечитывается она сама, но не на каждый кадр: агенты пишут пачками,
 *   и без склейки живость превратилась бы в шквал запросов (UI-72).
 * - Таблица пересобирает порядок строк, отсортированных по активности: строка
 *   из-под курсора уезжает, и промах по ссылке ведёт не туда. Здесь обновление
 *   предлагается полосой, а не навязывается.
 * - Экран проекта устроен как открытая задача: у него нет ни доски, ни таблицы,
 *   поэтому запись дела проекта перечитывает его сразу и целиком, без склейки и
 *   без полосы (UI-177). Страница области — так же (TRK-557).
 */
export interface Invalidation {
  /** Перечитывается сразу: обновление ничего не сдвигает. */
  immediate: QueryKey[];
  /** Перечитывается само, но не чаще раза в окно склейки: доска. */
  coalesced: QueryKey[];
  /** Ждёт просьбы человека: таблица. */
  deferred: QueryKey[];
}

/**
 * Что устарело от этой записи.
 *
 * Кадр в кэш не пишется: интерфейс не вычисляет за бэкенд (`CONCEPT.md`, 6). Признаки
 * задачи, счётчик вопросов и состав выдачи считаются на сервере из дела и связей —
 * дописать их «по кадру» значит однажды показать не то, что там на самом деле. Доска
 * поэтому не перекладывает карточку из столбца в столбец, а перечитывает свою выдачу.
 *
 * Ключи заданы префиксами: `['task', 'DEMO-6']` накрывает и пакет карточки, и ленту
 * дела, и прочитанные тела записей этой задачи; `taskKeys.board` — страницы всех
 * столбцов и числа над ними. `projectKeys.detail(key)` — тот же префикс `['project',
 * key]`, и он же накрывает карточку с атрибутами, страницы дела проекта и прочитанные
 * тела его записей (`entities/entry`, `entryKeys.projectCase`, `entryKeys.projectBody`).
 */
export function keysToInvalidate(frame: JournalFrame): Invalidation {
  // Запись дела проекта: своего списка и доски у проекта нет, перечитывается только
  // сам экран — карточка, атрибуты и опись (TRK-156, UI-177).
  if (frame.projectKey !== null) {
    return { immediate: [projectKeys.detail(frame.projectKey)], coalesced: [], deferred: [] };
  }

  // Запись дела области (TRK-557) — так же, как проекта: перечитывается страница
  // области сразу и целиком. И проект: правка и архив области — тоже записи его
  // дела, а раздел «Области» экрана проекта показывает название и признак архива.
  if (frame.area !== null) {
    return {
      immediate: [
        areaKeys.detail(frame.area),
        projectKeys.detail(splitAreaAddress(frame.area).projectKey),
      ],
      coalesced: [],
      deferred: [],
    };
  }

  /*
   * Запись дела обсуждения (TRK-672): перечитывается само обсуждение (карточка, лента,
   * тела), все списки обсуждений — входящая, история, блок в карточке задачи — и значок.
   * Вопрос и ответ обсуждения меняют признаки ожидания привязанных задач (`TRK#51`, п. 4),
   * а кадра в их деле нет, поэтому открытые карточки задач перечитываются разом; доска
   * и таблица — как от любой записи о задаче.
   */
  if (frame.discussion !== null) {
    return {
      immediate: [
        discussionKeys.detail(frame.discussion),
        discussionKeys.all,
        sessionKeys.bootstrap,
        ['task'],
      ],
      coalesced: [taskKeys.board],
      deferred: [taskKeys.table],
    };
  }

  // `taskKey` не назван вместе с `projectKey` быть не может: `parseFrame` такой кадр
  // уже отбросил. Ветка остаётся только для типов, а не как настоящая проверка.
  if (frame.taskKey === null) return { immediate: [], coalesced: [], deferred: [] };

  const immediate: QueryKey[] = [['task', frame.taskKey]];

  // Вопрос и ответ меняют «входящую» и счётчик в шапке. Это и есть «требует внимания»:
  // ради этого человек держит вкладку открытой, и ждать его согласия здесь нечего.
  if (frame.type === 'question' || frame.type === 'answer') {
    immediate.push(questionKeys.all, sessionKeys.bootstrap);
  }

  // Предупреждение и реакция на него — принятие или замечание — меняют раздел
  // «Требуют внимания» во входящей и число в значке (TRK-561): это тоже ход человека,
  // и ждёт он его так же, как вопроса.
  if (frame.type === 'warning' || frame.type === 'acceptance' || frame.type === 'remark') {
    immediate.push(taskKeys.attention, sessionKeys.bootstrap);
  }

  // Любая запись меняет `updated_at` задачи, а часто и её признаки: оба экрана списка
  // устаревают от чего угодно. Расходятся они не в том, устарели ли, а в том, что
  // стоит перестановка: на доске это предмет наблюдения, в таблице — шум.
  return { immediate, coalesced: [taskKeys.board], deferred: [taskKeys.table] };
}

/**
 * Что перечитать после обрыва связи.
 *
 * За время паузы могло случиться что угодно, а догонять пропущенные кадры поштучно
 * интерфейс не станет. Деление то же самое: открытая задача, открытый проект, входящая
 * и счётчик — сразу, доска — своим окном (одним перечитыванием, кадров-то нет), таблица
 * — по просьбе. Переподключение случается ровно тогда, когда человек ничего не делал,
 * и переставлять строки под ним особенно нечестно.
 */
export function keysAfterReconnect(): Invalidation {
  return {
    immediate: [
      ['task'],
      ['project'],
      ['area'],
      ['discussion'],
      discussionKeys.all,
      questionKeys.all,
      taskKeys.attention,
      sessionKeys.bootstrap,
    ],
    coalesced: [taskKeys.board],
    deferred: [taskKeys.table],
  };
}
