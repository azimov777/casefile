import type { QueryKey } from '@tanstack/react-query';

/**
 * Отложенные обновления: единственное место, где живёт правило «перечитать не сейчас».
 *
 * Сроков три, и они разведены по причине, а не по механизму:
 *
 * - **до возврата во вкладку** — перечитывать невидимое незачем, но и терять кадры
 *   нельзя: человек вернётся и должен увидеть то, что есть на самом деле;
 * - **до просьбы человека** — таблица меняет порядок и состав строк, а значит двигает
 *   то, на что человек смотрит. Обновление там предлагается, а не навязывается;
 * - **до конца окна склейки** — доска обновляется сама, но агенты пишут пачками: один
 *   заход по задаче это десяток записей за минуты, и перечитывание на каждый чужой
 *   кадр было бы шквалом запросов, а не живостью (UI-72).
 *
 * Все три выражены одной структурой и одними функциями: механизмы рядом разошлись бы
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

/**
 * Окно склейки: сколько ждать, прежде чем перечитать доску.
 *
 * Считается хвостом, а не передним фронтом: первый кадр заводит окно, все пришедшие
 * внутри него копятся, в конце уходит одно перечитывание. Передний фронт («первый
 * сразу, остальные пачкой») на пачке из десяти записей дал бы два перечитывания
 * вместо одного, а вся цена вопроса ровно в их числе.
 *
 * Секунда — потолок расхода: доска перечитывается не чаще раза в секунду, сколько бы
 * кадров ни пришло. Она же и вся задержка: от записи агента до переезда карточки
 * проходит окно плюс запрос. Для экрана, на который смотрят, как агенты разбирают
 * очередь, это незаметно, а для доски, стоящей открытой часами, — разница между
 * десятком запросов в минуту и сотней.
 */
export const COALESCE_WINDOW_MS = 1000;

type Slot = 'hidden' | 'request' | 'window';

function empty(): Held {
  return { keys: [], tasks: new Set(), vague: false };
}

const held: Record<Slot, Held> = { hidden: empty(), request: empty(), window: empty() };

/** Заведённое окно склейки. `null` означает «окна нет — следующий кадр его заведёт». */
let windowTimer: ReturnType<typeof setTimeout> | null = null;

type Listener = () => void;
const listeners = new Set<Listener>();
const closings = new Set<Listener>();

function notify(): void {
  for (const listener of listeners) listener();
}

function hold(slot: Slot, keys: QueryKey[], taskKey: string | null): void {
  held[slot].keys.push(...keys);
  if (taskKey === null) held[slot].vague = true;
  else held[slot].tasks.add(taskKey);
}

/**
 * Одинаковые ключи схлопываются: пачка кадров копит один и тот же префикс десять раз,
 * а инвалидация по нему десять раз подряд — это десять перечитываний, то есть ровно
 * то, от чего копили. Сравнение по содержанию: ключ — массив, и равных по смыслу
 * ссылок в нём не бывает.
 */
function unique(keys: QueryKey[]): QueryKey[] {
  const seen = new Set<string>();
  return keys.filter((key) => {
    const shape = JSON.stringify(key);
    if (seen.has(shape)) return false;
    seen.add(shape);
    return true;
  });
}

function release(slot: Slot): QueryKey[] {
  const from = held[slot];
  const wasEmpty = from.keys.length === 0 && !from.vague;
  held[slot] = empty();
  if (!wasEmpty) notify();
  return unique(from.keys);
}

/**
 * Отложить до возврата во вкладку. Сюда уходит всё, что при видимой вкладке
 * применилось бы само: счётчик вопросов, входящая, открытая задача, доска.
 */
export function holdWhileHidden(keys: QueryKey[]): void {
  if (keys.length === 0) return;
  hold('hidden', keys, null);
}

/**
 * Отложить до просьбы человека. `taskKey` — задача, из-за которой обновление
 * понадобилось; `null` означает «известно, что устарело, но не известно, из-за чего».
 */
export function holdForRequest(keys: QueryKey[], taskKey: string | null): void {
  if (keys.length === 0) return;
  hold('request', keys, taskKey);
  notify();
}

/**
 * Отложить до конца окна склейки. Первый кадр заводит окно; пришедшие следом попадают
 * в то же самое и второго не заводят — иначе окна наезжали бы друг на друга, и пачка
 * снова стоила бы столько перечитываний, сколько в ней кадров.
 */
export function holdForWindow(keys: QueryKey[]): void {
  if (keys.length === 0) return;
  hold('window', keys, null);
  if (windowTimer !== null) return;
  windowTimer = setTimeout(() => {
    windowTimer = null;
    for (const listener of closings) listener();
  }, COALESCE_WINDOW_MS);
}

/** Забрать накопленное за время, пока вкладка была скрыта. */
export function releaseHidden(): QueryKey[] {
  return release('hidden');
}

/** Забрать накопленное для таблицы: человек попросил показать новое. */
export function releaseRequested(): QueryKey[] {
  return release('request');
}

/** Забрать накопленное за окно склейки: окно закрылось. */
export function releaseWindowed(): QueryKey[] {
  return release('window');
}

/**
 * Сколько задач ждут показа. Снимок для `useSyncExternalStore`: число, а не объект,
 * — снимок обязан быть стабильным между отрисовками.
 */
export function requestedTaskCount(): number {
  return held.request.tasks.size;
}

/** Есть ли отложенное, о котором известно только то, что оно есть. */
export function requestedIsVague(): boolean {
  return held.request.vague;
}

export function subscribeDeferred(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** Кого будить, когда окно склейки закрылось. */
export function subscribeWindowClosed(listener: Listener): () => void {
  closings.add(listener);
  return () => {
    closings.delete(listener);
  };
}

/**
 * Забыть отложенное. Нужно тестам: состояние живёт в модуле и иначе пережило бы
 * тест, а падал бы следующий — на числе, которого он не накапливал, или на окне,
 * заведённом соседом.
 */
export function resetDeferred(): void {
  held.hidden = empty();
  held.request = empty();
  held.window = empty();
  if (windowTimer !== null) clearTimeout(windowTimer);
  windowTimer = null;
  notify();
}
