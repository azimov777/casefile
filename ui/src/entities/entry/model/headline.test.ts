import { describe, expect, it } from 'vitest';
import { ENTRY_TYPES, type EntryType } from '../api/entries';
import {
  ENTRY_TYPE_NAMES,
  entryHeadline,
  headlineText,
  type EntryFacts,
  type Headline,
} from './headline';

function built(type: EntryType, facts: EntryFacts): Headline {
  return entryHeadline(type, facts, 'DEMO-4');
}

/** Строка целиком: то, что человек прочитает глазами. */
function line(type: EntryType, facts: EntryFacts): string {
  return headlineText(built(type, facts));
}

/** Части, помеченные как идентификаторы контракта: они не переводятся. */
function ids(type: EntryType, facts: EntryFacts): string[] {
  const headline = built(type, facts);
  if (headline.kind !== 'built') return [];
  return headline.parts.filter((part) => part.kind === 'id').map((part) => part.text);
}

describe('заголовок записи по фактам', () => {
  it('у каждого типа контракта есть русское название', () => {
    // Словарь объявлен через `satisfies Record<EntryType, string>`: тип, добавленный
    // в контракт, ломает сборку. Здесь проверяется вторая половина — что ни одно
    // название не пустое и все они на русском.
    for (const type of ENTRY_TYPES) {
      const name = ENTRY_TYPE_NAMES[type];
      expect(name).not.toBe('');
      expect(name).toMatch(/^[а-яё\s]+$/i);
    }
  });

  it('переход называет оба конца и говорит, искать ли причину', () => {
    expect(line('status_changed', { from_status: 'open', to_status: 'done' })).toBe(
      'Статус open → done',
    );
    expect(
      line('status_changed', { from_status: 'open', to_status: 'backlog', has_reason: true }),
    ).toBe('Статус open → backlog · с причиной');

    // Статусы — идентификаторы контракта: их не переводят (`CONCEPT.md`, 6).
    expect(ids('status_changed', { from_status: 'open', to_status: 'done' })).toEqual([
      'open',
      'done',
    ]);
  });

  it('правка раздела и поля называет имя поля, а значения оставляет записи', () => {
    expect(line('section_changed', { field: 'goal' })).toBe('Правка раздела goal');
    expect(line('field_changed', { field: 'priority' })).toBe('Правка поля priority');
    expect(ids('section_changed', { field: 'goal' })).toEqual(['goal']);
  });

  it('смена исполнителя называет обоих, а отсутствие — словом', () => {
    expect(line('assignee_changed', { assignee_to: 'owner' })).toBe(
      'Исполнитель не назначен → owner',
    );
    expect(line('assignee_changed', { assignee_from: 'owner' })).toBe('Исполнитель owner → снят');
  });

  it('связь называет вид и вторую сторону ссылкой на неё', () => {
    const added = built('link_added', { link_kind: 'blocked_by', other_key: 'DEMO-2' });
    expect(headlineText(added)).toBe('Связь blocked_by DEMO-2');
    expect(added.kind === 'built' && added.parts.at(-1)).toEqual({
      kind: 'task',
      key: 'DEMO-2',
    });

    expect(line('link_removed', { link_kind: 'relates', other_key: 'DEMO-3' })).toBe(
      'Связь снята relates DEMO-3',
    );
  });

  it('ответ и вердикт тоже собираются здесь: их заголовок выводит трекер', () => {
    const answer = built('answer', { question_no: 4 });
    expect(headlineText(answer)).toBe('Ответ на DEMO-4#4');
    expect(answer.kind === 'built' && answer.parts.at(-1)).toEqual({
      kind: 'entry',
      key: 'DEMO-4',
      no: 4,
    });

    expect(line('verdict', { check_no: 3, outcome: 'failed' })).toBe('Обзорная проверка 3 failed');
    expect(ids('verdict', { check_no: 3, outcome: 'failed' })).toEqual(['failed']);
  });

  it('заведение задачи называется словами, без фактов', () => {
    expect(line('created', {})).toBe('Задача заведена');
  });

  it('у записи агента заголовок остаётся авторским, у сводки — выведенным', () => {
    for (const type of [
      'decision',
      'attempt',
      'finding',
      'artifact',
      'note',
      'question',
    ] as const) {
      expect(built(type, {}).kind).toBe('author');
    }
    // Заголовок сводки — первая строка «следующего шага»: в ленте он повторил бы тело.
    expect(built('summary', {}).kind).toBe('derived');
  });

  it('строка не разваливается на неполных фактах', () => {
    // Факты приходят от бэкенда, и старая запись может не знать нового поля. Пустое
    // место в строке лучше, чем `undefined` посреди фразы.
    expect(line('status_changed', {})).toBe('Статус не назначен → снят');
    expect(line('section_changed', {})).toBe('Правка раздела');
    expect(line('verdict', {})).toBe('Обзорная проверка ?');
  });
});
