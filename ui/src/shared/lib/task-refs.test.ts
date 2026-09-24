import { describe, expect, it } from 'vitest';
import { caseHref, projectHref, readEntryNo, splitTaskRefs, taskRefHref } from './task-refs';

describe('ссылки на задачи в тексте', () => {
  it('находит задачу и запись, сохраняя текст вокруг', () => {
    expect(splitTaskRefs('см. DEMO-2 и DEMO-6#4 — там всё')).toEqual([
      { kind: 'text', value: 'см. ' },
      { kind: 'ref', value: 'DEMO-2', href: '/tasks/DEMO-2' },
      { kind: 'text', value: ' и ' },
      { kind: 'ref', value: 'DEMO-6#4', href: '/tasks/DEMO-6?entry=4' },
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

  it('запись дела проекта `TRK#7` ведёт на экран проекта с раскрытой записью', () => {
    expect(splitTaskRefs('решено в TRK#7, см. и TRK-42#3')).toEqual([
      { kind: 'text', value: 'решено в ' },
      { kind: 'ref', value: 'TRK#7', href: '/projects/TRK?entry=7' },
      { kind: 'text', value: ', см. и ' },
      { kind: 'ref', value: 'TRK-42#3', href: '/tasks/TRK-42?entry=3' },
    ]);
  });

  it('ключ проекта без номера записи и строчные `trk#7` ссылкой не становятся', () => {
    expect(splitTaskRefs('проект TRK и trk#7')).toEqual([
      { kind: 'text', value: 'проект TRK и trk#7' },
    ]);
  });

  it('экран проекта — по ключу, запись — параметром `entry`', () => {
    expect(projectHref('TRK')).toBe('/projects/TRK');
    expect(projectHref('TRK', 7)).toBe('/projects/TRK?entry=7');
  });

  it('ведёт на карточку, а на запись — с её номером', () => {
    expect(taskRefHref({ key: 'DEMO-2', entryNo: null })).toBe('/tasks/DEMO-2');
    expect(taskRefHref({ key: 'DEMO-6', entryNo: 4 })).toBe('/tasks/DEMO-6?entry=4');
  });
});

describe('адрес записи собирается по одному правилу', () => {
  /**
   * Правило одно на всё приложение, и потребителей у него три: ссылка `TRK-42#12`
   * в тексте записи, уведомление о вопросе (UI-14) и подтверждение ответа (UI-15).
   * Все трое зовут `taskRefHref`, поэтому расходиться им нечем — а если кто-то
   * соберёт адрес руками, разойдётся молча.
   */
  it('ссылка на запись ведёт в карточку, ссылка на задачу — в задачу', () => {
    expect(taskRefHref({ key: 'DEMO-4', entryNo: 9 })).toBe('/tasks/DEMO-4?entry=9');
    expect(taskRefHref({ key: 'DEMO-4', entryNo: null })).toBe('/tasks/DEMO-4');
  });

  it('лента дела называет ту же запись тем же параметром', () => {
    expect(caseHref('DEMO-4', 9)).toBe('/tasks/DEMO-4/case?entry=9');
    expect(caseHref('DEMO-4')).toBe('/tasks/DEMO-4/case');
  });

  it('карточка и лента разбирают номер записи одинаково', () => {
    expect(readEntryNo('9')).toBe(9);
    expect(readEntryNo('0')).toBeNull();
    expect(readEntryNo('-1')).toBeNull();
    expect(readEntryNo('девять')).toBeNull();
    expect(readEntryNo(null)).toBeNull();
  });
});
