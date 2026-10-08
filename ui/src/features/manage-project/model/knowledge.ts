import { stateOfEntry, type Entry, type EntryState } from '@/entities/entry';

/** Какой список знания области: решения или заметки. */
export type KnowledgeKind = 'decisions' | 'notes';

/** Запись знания и её состояние: у `note` состояния нет — она действует всегда. */
export interface KnowledgeItem {
  entry: Entry;
  state: EntryState | null;
}

export interface KnowledgeList {
  inForce: KnowledgeItem[];
  superseded: KnowledgeItem[];
}

/**
 * Знание области, разложенное по спискам (TRK-660, TRK#59): решения — записи `decision`,
 * заметки — `finding` и прежние `note`. Действует ли запись, решил бэкенд при чтении
 * (`status`); здесь только раскладка. Запись без статуса (`note`) — действующая.
 */
export function knowledgeLists(entries: readonly Entry[]): Record<KnowledgeKind, KnowledgeList> {
  const lists: Record<KnowledgeKind, KnowledgeList> = {
    decisions: { inForce: [], superseded: [] },
    notes: { inForce: [], superseded: [] },
  };
  for (const entry of entries) {
    const kind: KnowledgeKind | null =
      entry.type === 'decision'
        ? 'decisions'
        : entry.type === 'finding' || entry.type === 'note'
          ? 'notes'
          : null;
    if (kind === null) continue;
    const state = stateOfEntry(entry);
    (state?.status === 'superseded' ? lists[kind].superseded : lists[kind].inForce).push({
      entry,
      state,
    });
  }
  return lists;
}
