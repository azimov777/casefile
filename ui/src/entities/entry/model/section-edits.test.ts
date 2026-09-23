import { describe, expect, it } from 'vitest';
import { say } from '@testing/say';
import { headlineText } from './headline';
import { groupSectionEdits, sectionEditsHeadline } from './section-edits';

const A = '11111111-1111-4111-8111-111111111111';
const B = '22222222-2222-4222-8222-222222222222';

function item(no: number, type: string, action_id: string | null = null) {
  return { no, type, action_id };
}

/** Раскладка групп в короткой записи: `[2,3,4]` — группа, число — одиночная запись. */
function shape(items: ReturnType<typeof item>[]) {
  return groupSectionEdits(items).map((run) =>
    run.kind === 'one' ? run.item.no : run.items.map((entry) => entry.no),
  );
}

describe('правки разделов одного действия', () => {
  it('подряд идущие section_changed одного action_id — одна группа', () => {
    const items = [
      item(1, 'created', A),
      ...[2, 3, 4, 5, 6, 7, 8].map((no) => item(no, 'section_changed', B)),
      item(9, 'decision', 'c'),
    ];
    const runs = groupSectionEdits(items);
    expect(shape(items)).toEqual([1, [2, 3, 4, 5, 6, 7, 8], 9]);
    expect(runs[1]).toMatchObject({ kind: 'sections', actionId: B, first: 2, last: 8 });
  });

  it('другие записи того же действия остаются на своих местах, группой не становятся', () => {
    // `update_task` с разделами и приоритетом: `field_changed` — не правка раздела.
    const items = [
      item(1, 'section_changed', A),
      item(2, 'section_changed', A),
      item(3, 'field_changed', A),
      item(4, 'status_changed', A),
    ];
    expect(shape(items)).toEqual([[1, 2], 3, 4]);
  });

  it('разные действия не сливаются, даже стоя вплотную', () => {
    const items = [
      item(1, 'section_changed', A),
      item(2, 'section_changed', A),
      item(3, 'section_changed', B),
      item(4, 'section_changed', B),
    ];
    expect(shape(items)).toEqual([
      [1, 2],
      [3, 4],
    ]);
  });

  it('одна правка группой не становится', () => {
    expect(shape([item(1, 'section_changed', A), item(2, 'decision', B)])).toEqual([1, 2]);
  });

  it('записи без признака (до его появления) не группируются никогда', () => {
    const items = [1, 2, 3].map((no) => item(no, 'section_changed', null));
    expect(shape(items)).toEqual([1, 2, 3]);
  });

  it('совпавшее время не читается вовсе: признак — только action_id', () => {
    const items = [
      { ...item(1, 'section_changed', A), created_at: 't' },
      { ...item(2, 'section_changed', B), created_at: 't' },
    ];
    expect(shape(items)).toEqual([1, 2]);
  });

  it('заголовок группы называет разделы как есть и по разу', () => {
    const headline = sectionEditsHeadline(['title', 'checks', 'checks', null], say.ui);
    expect(headlineText(headline)).toBe(`${say.ui('entry.headline.sectionsEdited')} title checks`);
    expect(
      headline.kind === 'built' && headline.parts.filter((part) => part.kind === 'id'),
    ).toEqual([
      { kind: 'id', text: 'title' },
      { kind: 'id', text: 'checks' },
    ]);
  });
});
