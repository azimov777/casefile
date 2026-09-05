import { describe, expect, it } from 'vitest';
import { splitTaskRefs, taskRefHref } from './task-refs';

describe('ссылки на задачи в тексте', () => {
  it('находит задачу и запись, сохраняя текст вокруг', () => {
    expect(splitTaskRefs('см. DEMO-2 и DEMO-6#4 — там всё')).toEqual([
      { kind: 'text', value: 'см. ' },
      { kind: 'ref', value: 'DEMO-2', ref: { key: 'DEMO-2', entryNo: null } },
      { kind: 'text', value: ' и ' },
      { kind: 'ref', value: 'DEMO-6#4', ref: { key: 'DEMO-6', entryNo: 4 } },
      { kind: 'text', value: ' — там всё' },
    ]);
  });

  it('текст без ссылок остаётся одним куском', () => {
    expect(splitTaskRefs('обычная строка')).toEqual([{ kind: 'text', value: 'обычная строка' }]);
  });

  it('не принимает за ссылку слова из строчных букв', () => {
    expect(splitTaskRefs('файл auth-2 и pull-42')).toEqual([
      { kind: 'text', value: 'файл auth-2 и pull-42' },
    ]);
  });

  it('ведёт на карточку, а на запись — с её номером', () => {
    expect(taskRefHref({ key: 'DEMO-2', entryNo: null })).toBe('/tasks/DEMO-2');
    expect(taskRefHref({ key: 'DEMO-6', entryNo: 4 })).toBe('/tasks/DEMO-6?entry=4');
  });
});
