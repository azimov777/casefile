import { describe, expect, it } from 'vitest';
import { TASK_PRIORITIES, TASK_STATUSES } from '../api/tasks';
import { TASK_PRIORITY_TONE, TASK_STATUS_TONE, priorityTone, statusTone } from './tones';

/**
 * Полноту соответствия держит `satisfies Record<...>` в `tones.ts`: убери оттуда
 * строку — и `pnpm typecheck` упадёт раньше любого теста. Здесь проверяется то,
 * чего компилятор не видит: что перечислены те же значения, что уходят в фильтры,
 * и что различимость статусов и приоритетов не потерялась при правке палитры.
 */
describe('тон задачи', () => {
  it('покрывает все статусы и приоритеты контракта', () => {
    expect(Object.keys(TASK_STATUS_TONE).sort()).toEqual([...TASK_STATUSES].sort());
    expect(Object.keys(TASK_PRIORITY_TONE).sort()).toEqual([...TASK_PRIORITIES].sort());
  });

  it('различает работу, завершение и снятие', () => {
    expect(TASK_STATUS_TONE.in_progress).not.toBe(TASK_STATUS_TONE.done);
    expect(TASK_STATUS_TONE.cancelled).not.toBe(TASK_STATUS_TONE.done);
  });

  it('различает critical и normal', () => {
    expect(TASK_PRIORITY_TONE.critical).not.toBe(TASK_PRIORITY_TONE.normal);
    expect(TASK_PRIORITY_TONE.high).not.toBe(TASK_PRIORITY_TONE.normal);
  });

  it('не красит обычный ход дел: открытая задача обычного приоритета вся нейтральна', () => {
    expect(statusTone('open')).toBe('neutral');
    expect(statusTone('backlog')).toBe('neutral');
    expect(priorityTone('normal')).toBe('neutral');
    expect(priorityTone('low')).toBe('neutral');
  });

  it('значение вне контракта показывается серым, а не роняет список', () => {
    expect(statusTone('неведомый')).toBe('neutral');
    expect(statusTone(null)).toBe('neutral');
    expect(priorityTone(undefined)).toBe('neutral');
  });
});
