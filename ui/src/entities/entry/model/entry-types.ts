import { ENTRY_TYPES, type EntryType } from '../api/entries';

/**
 * Типы записей из повторяющегося параметра адреса `?type=`: чужое значение
 * отбрасывается, как и в отборе задач. Один разбор на экран «Дело» задачи, дело
 * проекта и дело направления.
 */
export function readEntryTypes(values: string[]): EntryType[] {
  return values.filter((value): value is EntryType => (ENTRY_TYPES as string[]).includes(value));
}
