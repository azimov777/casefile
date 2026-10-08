import { describe, expect, it } from 'vitest';
import { holderTab, keepCaseTab, rememberOnTab, tabSearch } from './holder-tab';

/** Параметры адреса из строки: так их видит страница. */
const at = (search: string) => new URLSearchParams(search);

describe('вкладка из адреса (TRK-618, шаг 3)', () => {
  it('`tab` задан — открыта названная вкладка, даже если есть `entry` и `attribute`', () => {
    expect(holderTab(at('tab=decisions'), 'project')).toBe('decisions');
    expect(holderTab(at('tab=attributes'), 'project')).toBe('attributes');
    expect(holderTab(at('tab=areas'), 'project')).toBe('areas');
    expect(holderTab(at('tab=case'), 'project')).toBe('case');
    expect(holderTab(at('tab=decisions&entry=7&attribute=repo'), 'project')).toBe('decisions');
    expect(holderTab(at('tab=attributes'), 'area')).toBe('attributes');
    expect(holderTab(at('tab=decisions'), 'area')).toBe('decisions');
    expect(holderTab(at('tab=notes'), 'area')).toBe('notes');
    expect(holderTab(at('tab=case&attribute=channel'), 'area')).toBe('case');
  });

  it('`entry` без `tab` открывает «Дело» — и у проекта, и у области', () => {
    expect(holderTab(at('entry=7'), 'project')).toBe('case');
    expect(holderTab(at('entry=3'), 'area')).toBe('case');
    // Запись старше атрибута: ради неё пришли по ссылке `TRK#7`.
    expect(holderTab(at('attribute=repo&entry=7'), 'project')).toBe('case');
  });

  it('`attribute` без `tab` открывает «Атрибуты»', () => {
    expect(holderTab(at('attribute=repo'), 'project')).toBe('attributes');
    expect(holderTab(at('attribute=channel'), 'area')).toBe('attributes');
  });

  it('ничего нет — «Обзор» у проекта и «Решения» у области', () => {
    expect(holderTab(at(''), 'project')).toBe('overview');
    expect(holderTab(at(''), 'area')).toBe('decisions');
    // Чужие параметры (проход по пояснениям) вкладку не выбирают.
    expect(holderTab(at('walk=3'), 'project')).toBe('overview');
    // Негодный номер записи — не запись: вкладку он не перебивает.
    expect(holderTab(at('entry=abc'), 'project')).toBe('overview');
    expect(holderTab(at('attribute='), 'project')).toBe('overview');
  });

  it('неизвестный `tab` — вкладка по умолчанию, а не пустой экран', () => {
    expect(holderTab(at('tab=history'), 'project')).toBe('overview');
    expect(holderTab(at('tab='), 'project')).toBe('overview');
    // `overview` — не значение параметра: «Обзор» живёт без него.
    expect(holderTab(at('tab=overview'), 'area')).toBe('decisions');
    expect(holderTab(at('tab=history'), 'area')).toBe('decisions');
    // Явный, но неизвестный `tab` не уступает и записи: правило — «по умолчанию».
    expect(holderTab(at('tab=history&entry=7'), 'project')).toBe('overview');
  });

  it('область с `tab=areas` — «Решения»: такой вкладки у неё нет; `notes` нет у проекта', () => {
    expect(holderTab(at('tab=areas'), 'area')).toBe('decisions');
    expect(holderTab(at('tab=notes'), 'project')).toBe('overview');
  });
});

describe('адрес вкладки', () => {
  it('пишет `tab`, только когда без него открылась бы другая вкладка', () => {
    expect(tabSearch(at(''), 'project', 'decisions').toString()).toBe('tab=decisions');
    expect(tabSearch(at('tab=case'), 'project', 'overview').toString()).toBe('');
    expect(tabSearch(at(''), 'area', 'attributes').toString()).toBe('tab=attributes');
    expect(tabSearch(at('tab=attributes'), 'area', 'decisions').toString()).toBe('');
    expect(tabSearch(at(''), 'area', 'case').toString()).toBe('tab=case');
  });

  it('поиск `q` переезжает между «Решениями» и «Заметками» и снимается с остальных вкладок', () => {
    expect(tabSearch(at('q=шлюз'), 'area', 'notes').toString()).toBe(
      'q=%D1%88%D0%BB%D1%8E%D0%B7&tab=notes',
    );
    expect(tabSearch(at('tab=notes&q=a'), 'area', 'decisions').toString()).toBe('q=a');
    expect(tabSearch(at('q=a'), 'area', 'attributes').toString()).toBe('tab=attributes');
    expect(tabSearch(at('tab=notes&q=a'), 'area', 'case').toString()).toBe('tab=case');
  });

  it('снимает запись и атрибут чужой вкладки, свои оставляет', () => {
    expect(tabSearch(at('entry=7'), 'project', 'attributes').toString()).toBe('tab=attributes');
    expect(tabSearch(at('tab=attributes&attribute=repo'), 'project', 'case').toString()).toBe(
      'tab=case',
    );
    expect(tabSearch(at('entry=7'), 'project', 'case').toString()).toBe('entry=7');
    expect(tabSearch(at('attribute=repo'), 'project', 'attributes').toString()).toBe(
      'attribute=repo',
    );
    expect(tabSearch(at('attribute=repo&entry=7'), 'project', 'overview').toString()).toBe('');
  });

  it('отбор дела по типу (`type`) — состояние «Дела»: уход с него отбор снимает', () => {
    expect(tabSearch(at('tab=case&type=note'), 'project', 'decisions').toString()).toBe(
      'tab=decisions',
    );
    expect(tabSearch(at('tab=case&type=note'), 'project', 'case').toString()).toBe(
      'type=note&tab=case',
    );
    expect(tabSearch(at('type=note&type=decision'), 'area', 'attributes').toString()).toBe(
      'tab=attributes',
    );
  });

  it('чужие параметры адреса остаются', () => {
    expect(tabSearch(at('walk=3'), 'project', 'case').toString()).toBe('walk=3&tab=case');
  });
});

describe('раскрытие записи и атрибута не меняет вкладку', () => {
  it('свёрнутая запись, пришедшая ссылкой `?entry=N`, оставляет «Дело», а не «Обзор»', () => {
    expect(rememberOnTab(at('entry=7'), 'project', 'entry', null).toString()).toBe('tab=case');
    expect(rememberOnTab(at('attribute=repo'), 'project', 'attribute', null).toString()).toBe(
      'tab=attributes',
    );
  });

  it('раскрытие на своей вкладке только пишет номер или имя', () => {
    expect(rememberOnTab(at('tab=case'), 'project', 'entry', '5').toString()).toBe(
      'tab=case&entry=5',
    );
    expect(rememberOnTab(at('tab=case'), 'area', 'entry', '3').toString()).toBe('tab=case&entry=3');
    expect(rememberOnTab(at('entry=3'), 'area', 'entry', null).toString()).toBe('tab=case');
    expect(rememberOnTab(at('tab=attributes'), 'area', 'attribute', 'channel').toString()).toBe(
      'tab=attributes&attribute=channel',
    );
  });
});

describe('правка отбора по типу не уводит с «Дела»', () => {
  it('снятый отбор у дела, открытого записью или без `tab`, закрепляет `tab=case`', () => {
    expect(keepCaseTab(at(''), 'project').toString()).toBe('tab=case');
    expect(keepCaseTab(at('tab=case'), 'project').toString()).toBe('tab=case');
    expect(keepCaseTab(at('entry=5'), 'project').toString()).toBe('entry=5');
    // У области «Дело» не по умолчанию — так же закрепляется.
    expect(keepCaseTab(at(''), 'area').toString()).toBe('tab=case');
  });
});
