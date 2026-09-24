/**
 * Адрес записи в браузере: карточка задачи с раскрытой записью (UI-155).
 *
 * Один адрес на запись, откуда бы его ни скопировали — из описи или из ленты дела:
 * получатель видит один и тот же экран. Карточка, а не дело: она открывается пакетом
 * и одним телом записи, а сводка и вопросы задачи видны рядом. Параметр `entry` —
 * тот же, которым карточка сама помнит раскрытое (`task-page.tsx`, `rememberOpen`).
 *
 * Путь от корня источника: у приложения нет ни `base` в сборке, ни `basename` у роутера.
 */
export function entryAddress(taskKey: string, no: number, origin: string): string {
  const url = new URL(`/tasks/${encodeURIComponent(taskKey)}`, origin);
  url.searchParams.set('entry', String(no));
  return url.href;
}
