import type { TaskFeatures } from '../api/tasks';

/**
 * Есть ли у задачи хоть один значок признака. Пустая ячейка признаков — это «ничего
 * не требует внимания», и место под неё в карточке доски занимать незачем.
 *
 * Решение одно на строку и карточку: разъехавшись, они показывали бы разное об одном
 * и том же. Лежит отдельно от компонента, как и `columns.ts`: файл, экспортирующий
 * и компонент, и функцию, ломает горячую перезагрузку.
 */
export function hasFeatureBadges(features: TaskFeatures): boolean {
  return (
    features.blocked ||
    features.open_questions > 0 ||
    features.open_blocking_questions > 0 ||
    features.open_remarks > 0
  );
}
