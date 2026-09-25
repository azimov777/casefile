/**
 * Предел описания проекта в знаках (`../docs/CONCEPT.md`, 3.2): короткое «что это»,
 * которое едет в карточке каждой задачи проекта.
 *
 * Числом в контракте его нет — у поля `description` схема не объявляет `maxLength`,
 * потому что бэкенд меряет строку **после** обрезки пробелов по краям, а схема так не
 * умеет. Источник истины — `MAX_PROJECT_DESCRIPTION_LENGTH` в
 * `../app/domain/projects.py`; здесь его копия ради одного: показать остаток, пока
 * человек пишет. Отказ `project_description_too_long` по-прежнему решает бэкенд.
 */
export const PROJECT_DESCRIPTION_LIMIT = 320;

/**
 * Длина описания так, как её меряет бэкенд: кодовые точки строки без пробелов по краям
 * (`len(description.strip())`). `String.length` считает половинки суррогатных пар и
 * эмодзи засчитал бы за два знака, а бэкенд — за один.
 */
export function descriptionLength(description: string): number {
  return [...description.trim()].length;
}

/** Длиннее ли описание предела: тогда окно не отправляет его вовсе. */
export function descriptionTooLong(description: string): boolean {
  return descriptionLength(description) > PROJECT_DESCRIPTION_LIMIT;
}
