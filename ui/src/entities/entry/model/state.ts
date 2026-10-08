import { areaHref, discussionHref, projectHref } from '@/shared/lib';
import type { DecisionStatus } from '../ui/decision-status';
import type { Entry } from '../api/entries';
import type { EntryOwner } from './owner';

/**
 * Состояние записи знания, как его отдал бэкенд при чтении дела проекта или области:
 * действует ли она и какая запись её заменила (TRK#57, §5). Интерфейс ничего не вычисляет —
 * только берёт два поля записи.
 */
export interface EntryState {
  status: DecisionStatus;
  /** Номер записи того же дела, заменившей эту; `null`, пока действует. */
  supersededBy: number | null;
}

/**
 * Состояние записи, если у неё оно есть: у решения и находки дела проекта или области.
 * У остальных записей и в деле задачи бэкенд отдаёт `null` — состояния нет, и пометка не
 * рисуется.
 */
export function stateOfEntry(entry: Entry): EntryState | null {
  if (entry.type !== 'decision' && entry.type !== 'finding') return null;
  if (entry.status == null) return null;
  return { status: entry.status, supersededBy: entry.superseded_by ?? null };
}

/** Адрес записи дела проекта или области внутри приложения: экран владельца с `?entry=N`. */
export function knowledgeEntryHref(owner: EntryOwner, no: number): string {
  if (owner.kind === 'area') return areaHref(owner.key, no);
  if (owner.kind === 'discussion') return discussionHref(owner.key, no);
  return projectHref(owner.key, no);
}
