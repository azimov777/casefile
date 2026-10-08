import { describe, expect, it } from 'vitest';
import { entryOfType } from '@testing/msw/responses';
import type { Entry } from '../api/entries';
import { draftOfEntry, liftedByHref } from './draft';

function withDraft(type: 'decision' | 'finding', draftFor: string | null, liftedBy?: string[]) {
  return {
    ...entryOfType(1, 'DEMO-1', type),
    payload: { supersedes: [], draft_for: draftFor },
    lifted_by: liftedBy,
  } as Entry;
}

describe('черновик знания (TRK-661)', () => {
  it('решение и находка с адресом подъёма — черновики, поднятость берётся из lifted_by', () => {
    expect(draftOfEntry(withDraft('decision', 'DEMO/core', ['DEMO/core#4']))).toEqual({
      address: 'DEMO/core',
      liftedBy: ['DEMO/core#4'],
    });
    expect(draftOfEntry(withDraft('finding', 'DEMO', []))).toEqual({
      address: 'DEMO',
      liftedBy: [],
    });
  });

  it('запись без адреса подъёма и запись другого типа черновиком не считаются', () => {
    expect(draftOfEntry(withDraft('decision', null))).toBeNull();
    expect(draftOfEntry(entryOfType(1, 'DEMO-1', 'summary'))).toBeNull();
  });

  it('адрес записи адресата ведёт на страницу области или проекта', () => {
    expect(liftedByHref('DEMO/core#4')).toBe('/projects/DEMO/areas/core?entry=4');
    expect(liftedByHref('DEMO#9')).toBe('/projects/DEMO?entry=9');
    expect(liftedByHref('чужое')).toBeNull();
  });
});
