import { describe, expect, it } from 'vitest';
import { columnCondition, columnRequest, isAwaitingAnswer } from './waiting';

const features = (blocking: number) =>
  ({
    blocked: false,
    open_questions: blocking,
    open_blocking_questions: blocking,
    open_remarks: 0,
    open_warnings: 0,
    last_summary_at: null,
    last_entry_at: null,
  }) as never;

describe('условие столбца доски', () => {
  it('«Ждёт ответа» — вопрос blocking у задачи из работы или старый статус', () => {
    const condition = columnCondition('waiting') ?? '';
    expect(condition).toContain('status: in backlog, open, in_progress');
    expect(condition).toContain('open_blocking_questions: > 0');
    expect(condition).toContain('or status: waiting');
  });

  it('столбцы работы исключают такие задачи, закрытые — не трогают', () => {
    for (const status of ['backlog', 'open', 'in_progress'] as const) {
      expect(columnCondition(status)).toBe('open_blocking_questions: 0');
    }
    expect(columnCondition('done')).toBeNull();
    expect(columnCondition('cancelled')).toBeNull();
  });

  it('у «Ждёт ответа» статуса в отборе нет, у прочих он остаётся', () => {
    expect(columnRequest('waiting', {}).status).toBeUndefined();
    expect(columnRequest('open', {}).status).toEqual(['open']);
    expect(columnRequest('open', {}).column).toBe('open');
  });
});

describe('пометка «ждёт ответа»', () => {
  it('есть при открытом вопросе blocking, нет без него', () => {
    expect(isAwaitingAnswer('open', features(1))).toBe(true);
    expect(isAwaitingAnswer('open', features(0))).toBe(false);
  });

  it('есть и у старого статуса waiting; закрытой задаче не ставится', () => {
    expect(isAwaitingAnswer('waiting', features(0))).toBe(true);
    expect(isAwaitingAnswer('done', features(1))).toBe(false);
  });
});
