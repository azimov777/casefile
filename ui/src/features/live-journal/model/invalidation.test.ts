import { describe, expect, it } from 'vitest';
import { questionKeys, type Entry, type EntryType } from '@/entities/entry';
import { projectKeys } from '@/entities/project';
import { sessionKeys } from '@/entities/session';
import { taskKeys } from '@/entities/task';
import type { JournalFrame } from './frames';
import { keysAfterReconnect, keysToInvalidate } from './invalidation';

/**
 * Кадр живого потока для теста: `keysToInvalidate` смотрит только на `type`, `taskKey`
 * и `projectKey` — тело записи ей не нужно.
 */
function frame(
  type: EntryType,
  owner: { taskKey: string | null; projectKey: string | null },
): JournalFrame {
  return { seq: 1, type, entry: {} as Entry, ...owner };
}

describe('keysToInvalidate — запись дела проекта', () => {
  it('помечает устаревшим только префикс проекта, ключи задач не трогает (UI-177)', () => {
    const result = keysToInvalidate(
      frame('attribute_changed', { taskKey: null, projectKey: 'TRK' }),
    );

    expect(result).toEqual({
      immediate: [projectKeys.detail('TRK')],
      coalesced: [],
      deferred: [],
    });
  });

  it('архивирование и восстановление перечитывают тот же префикс проекта', () => {
    const archived = keysToInvalidate(frame('archived', { taskKey: null, projectKey: 'TRK' }));
    const restored = keysToInvalidate(frame('restored', { taskKey: null, projectKey: 'TRK' }));

    expect(archived.immediate).toEqual([projectKeys.detail('TRK')]);
    expect(restored.immediate).toEqual([projectKeys.detail('TRK')]);
  });
});

describe('keysToInvalidate — запись дела задачи', () => {
  it('помечает устаревшей задачу сразу, доску — окном, таблицу — по просьбе', () => {
    const result = keysToInvalidate(frame('note', { taskKey: 'DEMO-1', projectKey: null }));

    expect(result).toEqual({
      immediate: [['task', 'DEMO-1']],
      coalesced: [taskKeys.board],
      deferred: [taskKeys.table],
    });
  });

  it('вопрос и ответ дополнительно поднимают входящую и счётчик в шапке', () => {
    const question = keysToInvalidate(frame('question', { taskKey: 'DEMO-1', projectKey: null }));
    const answer = keysToInvalidate(frame('answer', { taskKey: 'DEMO-1', projectKey: null }));

    expect(question.immediate).toEqual([
      ['task', 'DEMO-1'],
      questionKeys.all,
      sessionKeys.bootstrap,
    ]);
    expect(answer.immediate).toEqual([['task', 'DEMO-1'], questionKeys.all, sessionKeys.bootstrap]);
  });
});

describe('keysAfterReconnect', () => {
  it('после обрыва перечитывает разом и задачи, и проекты — что случилось, неизвестно', () => {
    const result = keysAfterReconnect();

    expect(result.immediate).toEqual([
      ['task'],
      ['project'],
      questionKeys.all,
      sessionKeys.bootstrap,
    ]);
    expect(result.coalesced).toEqual([taskKeys.board]);
    expect(result.deferred).toEqual([taskKeys.table]);
  });
});
