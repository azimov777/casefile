import { describe, expect, it } from 'vitest';
import { tasksHref } from './href';

describe('адрес списка', () => {
  it('меняет вид, не трогая остальные условия', () => {
    const href = tasksHref('queue=UI&status=open&status=done&assignee=owner&sort=key', {
      view: 'board',
    });
    const params = new URLSearchParams(href.slice('/tasks?'.length));

    expect(params.get('view')).toBe('board');
    expect(params.get('queue')).toBe('UI');
    expect(params.getAll('status')).toEqual(['open', 'done']);
    expect(params.getAll('assignee')).toEqual(['owner']);
    expect(params.get('sort')).toBe('key');
  });

  it('возвращает с доски в таблицу тот же отбор', () => {
    const board = tasksHref('queue=UI&priority=high', { view: 'board' });
    const back = tasksHref(board.slice('/tasks?'.length), { view: 'table' });

    expect(back).toBe('/tasks?queue=UI&priority=high');
  });

  it('номер страницы не переносится: он указывает на место в другой выдаче', () => {
    expect(tasksHref('queue=UI&page=3', { view: 'board' })).toBe('/tasks?view=board&queue=UI');
    // И даже без изменений: возврат в раздел ведёт к началу списка, а не в середину.
    expect(tasksHref('queue=UI&page=3')).toBe('/tasks?queue=UI');
  });

  it('но переносится, когда меняют как раз его: этим и листается список', () => {
    expect(tasksHref('queue=UI&status=open&page=2', { page: 3 })).toBe(
      '/tasks?queue=UI&status=open&page=3',
    );
    expect(tasksHref('queue=UI&page=2', { page: 1 })).toBe('/tasks?queue=UI');
  });

  it('старый курсор в адрес не переезжает: страница адресуется номером', () => {
    expect(tasksHref('queue=UI&cursor=page-2', { page: 2 })).toBe('/tasks?queue=UI&page=2');
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
