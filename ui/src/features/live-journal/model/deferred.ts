import type { QueryKey } from '@tanstack/react-query';

/**
 * Отложенные обновления: единственное место, где живёт правило «перечитать не сейчас».
 *
 * Откладываний два по причине, а не по механизму:
 *
 * - **до возврата во вкладку** — перечитывать невидимое незачем, но и терять кадры
 *   нельзя: человек вернётся и должен увидеть то, что есть на самом деле;
 * - **до просьбы человека** — список и доска меняют порядок и состав строк, а значит
 *   двигают то, на что человек смотрит. Обновление там предлагается, а не навязывается.
 *
 * Оба выражены одной структурой и одними функциями: два механизма рядом разошлись бы
 * при первой же правке, и один из них перестал бы считать то, что копит другой.
 */
interface Held {
  keys: QueryKey[];
  /** Задачи, которых коснулись изменения: по ним считается число в полосе. */
  tasks: Set<string>;
  /**
   * Что именно изменилось, неизвестно. Так приходит переподключение: за время обрыва
   * могло случиться что угодно, а числа для полосы взять неоткуда.
   */
  vague: boolean;
}

function empty(): Held {
  return { keys: [], tasks: new Set(), vague: false };
}

/** Ждёт возврата человека во вкладку. */
let hidden = empty();
/** Ждёт того, что человек сам попросит показать новое. */
let list = empty();

type Listener = () => void;
const listeners = new Set<Listener>();

function notify(): void {
  for (const listener of listeners) listener();
}

function hold(into: Held, keys: QueryKey[], taskKey: string | null): void {
  into.keys.push(...keys);
  if (taskKey === null) into.vague = true;
  else into.tasks.add(taskKey);
}

function release(from: Held): QueryKey[] {
  const keys = from.keys;
  const wasEmpty = keys.length === 0 && !from.vague;
  if (from === hidden) hidden = empty();
  else list = empty();
  if (!wasEmpty) notify();
  return keys;
}

/**
 * Отложить до возврата во вкладку. Сюда уходит всё, что при видимой вкладке
 * применилось бы сразу: счётчик вопросов, входящая, открытая задача.
 */
export function holdWhileHidden(keys: QueryKey[]): void {
  if (keys.length === 0) return;
  hold(hidden, keys, null);
}

/**
 * Отложить до просьбы человека. `taskKey` — задача, из-за которой обновление
 * понадобилось; `null` означает «известно, что устарело, но не известно, из-за чего».
 */
export function holdForRequest(keys: QueryKey[], taskKey: string | null): void {
  if (keys.length === 0) return;
  hold(list, keys, taskKey);
  notify();
}

/** Забрать накопленное за время, пока вкладка была скрыта. */
export function releaseHidden(): QueryKey[] {
  return release(hidden);
}

/** Забрать накопленное для списка: человек попросил показать новое. */
export function releaseRequested(): QueryKey[] {
  return release(list);
}

/**
 * Сколько задач ждут показа. Снимок для `useSyncExternalStore`: число, а не объект,
 * — снимок обязан быть стабильным между отрисовками.
 */
export function requestedTaskCount(): number {
  return list.tasks.size;
}

/** Есть ли отложенное, о котором известно только то, что оно есть. */
export function requestedIsVague(): boolean {
  return list.vague;
}

export function subscribeDeferred(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/**
 * Забыть отложенное. Нужно тестам: состояние живёт в модуле и иначе пережило бы
 * тест, а падал бы следующий — на числе, которого он не накапливал.
 */
export function resetDeferred(): void {
  hidden = empty();
  list = empty();
  notify();
}
