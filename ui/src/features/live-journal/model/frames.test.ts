import { describe, expect, it } from 'vitest';
import { parseFrame } from './frames';

/** Тело кадра: та же запись, что отдаёт лента; поля, лишние для разбора, опущены. */
function frame(owner: { task_key: string | null; project_key: string | null }): string {
  return JSON.stringify({ seq: 7, no: 2, type: 'note', title: 'Заметка', ...owner });
}

describe('parseFrame', () => {
  it('разбирает запись задачи', () => {
    expect(parseFrame(frame({ task_key: 'TRK-1', project_key: null }))).toMatchObject({
      seq: 7,
      type: 'note',
      taskKey: 'TRK-1',
    });
  });

  it('молча отбрасывает запись дела проекта: у неё нет ключа задачи (TRK-156)', () => {
    expect(parseFrame(frame({ task_key: null, project_key: 'TRK' }))).toBeNull();
  });

  it('отбрасывает негодный кадр, не бросая', () => {
    expect(parseFrame('не json')).toBeNull();
  });
});
