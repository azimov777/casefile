import { describe, expect, it } from 'vitest';
import { tasksHref } from './href';

describe('адрес списка', () => {
  it('меняет вид, не трогая остальные условия', () => {
    const href = tasksHref('queue=UI&status=open&status=done&tags=ux&sort=key', { view: 'board' });
    const params = new URLSearchParams(href.slice('/tasks?'.length));

    expect(params.get('view')).toBe('board');
    expect(params.get('queue')).toBe('UI');
    expect(params.getAll('status')).toEqual(['open', 'done']);
    expect(params.getAll('tags')).toEqual(['ux']);
    expect(params.get('sort')).toBe('key');
  });

  it('возвращает с доски в таблицу тот же отбор', () => {
    const board = tasksHref('queue=UI&priority=high', { view: 'board' });
    const back = tasksHref(board.slice('/tasks?'.length), { view: 'table' });

    expect(back).toBe('/tasks?queue=UI&priority=high');
  });

  it('курсор не переносится: он указывает на страницу другой выдачи', () => {
    expect(tasksHref('queue=UI&cursor=page-2', { view: 'board' })).toBe(
      '/tasks?view=board&queue=UI',
    );
    // И даже без изменений: возврат в раздел ведёт к началу списка, а не в середину.
    expect(tasksHref('queue=UI&cursor=page-2')).toBe('/tasks?queue=UI');
  });

  it('без условий даёт чистый адрес раздела', () => {
    expect(tasksHref('')).toBe('/tasks');
    expect(tasksHref(new URLSearchParams())).toBe('/tasks');
  });

  it('чужие параметры адреса в отбор не попадают', () => {
    // `entry` живёт на карточке задачи; в списке он ничего не значит и уезжать
    // в его адрес не должен.
    expect(tasksHref('entry=12&queue=UI')).toBe('/tasks?queue=UI');
  });
});
