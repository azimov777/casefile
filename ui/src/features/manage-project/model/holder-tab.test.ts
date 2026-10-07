import { describe, expect, it } from 'vitest';
import { holderTab, rememberOnTab, tabSearch } from './holder-tab';

/** Параметры адреса из строки: так их видит страница. */
const at = (search: string) => new URLSearchParams(search);

describe('вкладка из адреса (TRK-618, шаг 3)', () => {
  it('`tab` задан — открыта названная вкладка, даже если есть `entry` и `attribute`', () => {
    expect(holderTab(at('tab=decisions'), 'project')).toBe('decisions');
    expect(holderTab(at('tab=attributes'), 'project')).toBe('attributes');
    expect(holderTab(at('tab=directions'), 'project')).toBe('directions');
    expect(holderTab(at('tab=case'), 'project')).toBe('case');
    expect(holderTab(at('tab=decisions&entry=7&attribute=repo'), 'project')).toBe('decisions');
    expect(holderTab(at('tab=attributes'), 'direction')).toBe('attributes');
    expect(holderTab(at('tab=case&attribute=channel'), 'direction')).toBe('case');
  });

  it('`entry` без `tab` открывает «Дело» — и у проекта, и у направления', () => {
    expect(holderTab(at('entry=7'), 'project')).toBe('case');
    expect(holderTab(at('entry=3'), 'direction')).toBe('case');
    // Запись старше атрибута: ради неё пришли по ссылке `TRK#7`.
    expect(holderTab(at('attribute=repo&entry=7'), 'project')).toBe('case');
  });

  it('`attribute` без `tab` открывает «Атрибуты»', () => {
    expect(holderTab(at('attribute=repo'), 'project')).toBe('attributes');
    expect(holderTab(at('attribute=channel'), 'direction')).toBe('attributes');
  });

  it('ничего нет — «Обзор» у проекта и «Дело» у направления', () => {
    expect(holderTab(at(''), 'project')).toBe('overview');
    expect(holderTab(at(''), 'direction')).toBe('case');
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
    expect(holderTab(at('tab=overview'), 'direction')).toBe('case');
    expect(holderTab(at('tab=history'), 'direction')).toBe('case');
    // Явный, но неизвестный `tab` не уступает и записи: правило — «по умолчанию».
    expect(holderTab(at('tab=history&entry=7'), 'project')).toBe('overview');
  });

  it('направление с `tab=decisions` или `tab=directions` — «Дело»: этих вкладок у него нет', () => {
    expect(holderTab(at('tab=decisions'), 'direction')).toBe('case');
    expect(holderTab(at('tab=directions'), 'direction')).toBe('case');
  });
});

describe('адрес вкладки', () => {
  it('пишет `tab`, только когда без него открылась бы другая вкладка', () => {
    expect(tabSearch(at(''), 'project', 'decisions').toString()).toBe('tab=decisions');
    expect(tabSearch(at('tab=case'), 'project', 'overview').toString()).toBe('');
    expect(tabSearch(at(''), 'direction', 'attributes').toString()).toBe('tab=attributes');
    expect(tabSearch(at('tab=attributes'), 'direction', 'case').toString()).toBe('');
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
    expect(rememberOnTab(at(''), 'direction', 'entry', '3').toString()).toBe('entry=3');
    expect(rememberOnTab(at('entry=3'), 'direction', 'entry', null).toString()).toBe('');
    expect(
      rememberOnTab(at('tab=attributes'), 'direction', 'attribute', 'channel').toString(),
    ).toBe('tab=attributes&attribute=channel');
  });
});
