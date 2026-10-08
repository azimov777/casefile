import { describe, expect, it } from 'vitest';
import type { Entry } from '@/entities/entry';
import { knowledgeLists } from './knowledge';

function entry(
  no: number,
  type: Entry['type'],
  status: 'in_force' | 'superseded' | null,
  by: number | null = null,
) {
  return {
    no,
    type,
    title: `Запись ${no}`,
    body: '',
    status,
    superseded_by: by,
  } as unknown as Entry;
}

describe('знание области по спискам', () => {
  it('решения и заметки врозь, действующие и заменённые врозь', () => {
    const lists = knowledgeLists([
      entry(1, 'decision', 'superseded', 4),
      entry(2, 'finding', 'in_force'),
      entry(3, 'note', null),
      entry(4, 'decision', 'in_force'),
      entry(5, 'finding', 'superseded', 6),
      entry(6, 'finding', 'in_force'),
      entry(7, 'artifact', null),
      entry(8, 'attribute_created', null),
    ]);
    expect(lists.decisions.inForce.map((item) => item.entry.no)).toEqual([4]);
    expect(lists.decisions.superseded.map((item) => item.entry.no)).toEqual([1]);
    expect(lists.decisions.superseded[0]?.state).toEqual({ status: 'superseded', supersededBy: 4 });
    expect(lists.notes.inForce.map((item) => item.entry.no)).toEqual([2, 3, 6]);
    expect(lists.notes.superseded.map((item) => item.entry.no)).toEqual([5]);
  });

  it('заметка типа note без статуса действует и пометки не несёт', () => {
    const lists = knowledgeLists([entry(3, 'note', null)]);
    expect(lists.notes.inForce[0]?.state).toBeNull();
  });
});
