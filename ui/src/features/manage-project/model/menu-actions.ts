/*
 * Пункты меню «⋯» экрана проекта и страницы направления (TRK-618, решение TRK#46): что
 * стоит в меню при каком состоянии. Действий не прибавилось и не убавилось — они переехали
 * из строки шапки в меню.
 */

/** Пункт меню: правка, архив или восстановление. */
export type MenuAction = 'edit' | 'archive' | 'restore';

/** Пункты меню проекта: у активного — «Изменить» и «В архив», у архивного — «Восстановить». */
export function projectMenuActions(archived: boolean): MenuAction[] {
  return archived ? ['restore'] : ['edit', 'archive'];
}

/**
 * Пункты меню направления. Правка — когда запись открыта и ни направление, ни проект не в
 * архиве (`canEdit`); архив или восстановление — когда проект не в архиве (`canArchive`):
 * восстановить направление архивного проекта нельзя (`project_archived`).
 */
export function directionMenuActions({
  canEdit,
  canArchive,
  archived,
}: {
  canEdit: boolean;
  canArchive: boolean;
  archived: boolean;
}): MenuAction[] {
  const actions: MenuAction[] = [];
  if (canEdit) actions.push('edit');
  if (canArchive) actions.push(archived ? 'restore' : 'archive');
  return actions;
}
