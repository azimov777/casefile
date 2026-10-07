import { describe, expect, it } from 'vitest';
import { parseFrame } from './frames';

/** Тело кадра: та же запись, что отдаёт лента; поля, лишние для разбора, опущены. */
function frame(owner: {
  task_key: string | null;
  project_key: string | null;
  area?: string | null;
  discussion?: string | null;
}): string {
  return JSON.stringify({ seq: 7, no: 2, type: 'note', title: 'Заметка', ...owner });
}

describe('parseFrame', () => {
  it('разбирает запись задачи', () => {
    expect(parseFrame(frame({ task_key: 'TRK-1', project_key: null }))).toMatchObject({
      seq: 7,
      type: 'note',
      taskKey: 'TRK-1',
      projectKey: null,
    });
  });

  it('разбирает запись дела проекта: ключ задачи `null`, назван ключ проекта (UI-177)', () => {
    expect(parseFrame(frame({ task_key: null, project_key: 'TRK' }))).toMatchObject({
      seq: 7,
      type: 'note',
      taskKey: null,
      projectKey: 'TRK',
    });
  });

  it('разбирает запись дела области: назван её адрес (TRK-557)', () => {
    expect(
      parseFrame(frame({ task_key: null, project_key: null, area: 'TRK/promotion' })),
    ).toMatchObject({ taskKey: null, projectKey: null, area: 'TRK/promotion' });
  });

  it('разбирает запись дела обсуждения: назван его адрес (TRK-672)', () => {
    expect(
      parseFrame(frame({ task_key: null, project_key: null, discussion: 'TRK~7' })),
    ).toMatchObject({ taskKey: null, projectKey: null, area: null, discussion: 'TRK~7' });
  });

  it('отбрасывает кадр без владельца: ни задачи, ни проекта', () => {
    expect(parseFrame(frame({ task_key: null, project_key: null }))).toBeNull();
  });

  it('отбрасывает негодный кадр, не бросая', () => {
    expect(parseFrame('не json')).toBeNull();
  });
});
