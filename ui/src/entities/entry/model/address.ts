import { directionHref } from '@/shared/lib';
import type { EntryOwner } from './owner';

/**
 * Адрес записи в браузере: экран владельца с раскрытой записью (UI-155, UI-174).
 *
 * Один адрес на запись, откуда бы его ни скопировали — из описи или из ленты дела:
 * получатель видит один и тот же экран. Карточка задачи, а не дело: она открывается
 * пакетом и одним телом записи, а сводка и вопросы задачи видны рядом. Запись дела
 * проекта открывается на экране проекта — ленты у него нет, запись дела направления — на
 * странице направления (TRK-557). Параметр `entry` — тот же,
 * которым экран сам помнит раскрытое (`task-page.tsx`, `rememberOpen`).
 *
 * Путь от корня источника: у приложения нет ни `base` в сборке, ни `basename` у роутера.
 */
export function entryAddress(owner: EntryOwner, no: number, origin: string): string {
  // Направление — под своим проектом (`directionHref`): адрес `TRK/promotion` несёт
  // косую черту, и кодировать её в один сегмент значило бы получить путь, которого нет.
  const path =
    owner.kind === 'direction'
      ? directionHref(owner.key)
      : `/${owner.kind === 'task' ? 'tasks' : 'projects'}/${encodeURIComponent(owner.key)}`;
  const url = new URL(path, origin);
  url.searchParams.set('entry', String(no));
  return url.href;
}
