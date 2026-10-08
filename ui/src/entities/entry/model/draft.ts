import { areaHref, projectHref } from '@/shared/lib';
import type { Entry } from '../api/entries';

/**
 * Черновик знания в деле задачи (TRK-661, TRK#57, §8): решение или находка, которую
 * автор пометил адресом подъёма — проектом `TRK` или областью `TRK/mcp`. Подъём — запись
 * дела адресата со ссылкой на черновик; есть ли она, считает бэкенд при чтении дела
 * (`lifted_by`), интерфейс подъём сам не ищет (TRK#13).
 */
export interface DraftState {
  /** Дело, в которое черновик предстоит поднять: ключ проекта или адрес области. */
  address: string;
  /** Записи адресата, поднявшие черновик, `TRK/mcp#5`; пусто — не поднят. */
  liftedBy: string[];
}

/**
 * Состояние черновика, если запись — черновик: у решения и находки в деле задачи с
 * `payload.draft_for`. Остальные записи, а также запись без адреса подъёма — обычное
 * решение или находка — черновиком не считаются.
 */
export function draftOfEntry(entry: Entry): DraftState | null {
  if (entry.type !== 'decision' && entry.type !== 'finding') return null;
  const address = entry.payload?.draft_for;
  if (address == null || address === '') return null;
  return { address, liftedBy: entry.lifted_by ?? [] };
}

/**
 * Адрес записи адресата `TRK/mcp#5` или `TRK#5` в приложении: страница области или
 * проекта с раскрытой записью. Строка, которую нельзя разобрать, ссылкой не станет —
 * `null`, и вызывающий покажет её текстом.
 */
export function liftedByHref(reference: string): string | null {
  const match = /^(.+)#(\d+)$/.exec(reference);
  if (match?.[1] === undefined || match[2] === undefined) return null;
  const owner = match[1];
  const no = Number(match[2]);
  return owner.includes('/') ? areaHref(owner, no) : projectHref(owner, no);
}
