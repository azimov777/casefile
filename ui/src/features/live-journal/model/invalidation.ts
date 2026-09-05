import type { QueryKey } from '@tanstack/react-query';
import { questionKeys } from '@/entities/entry';
import { sessionKeys } from '@/entities/session';
import { taskKeys } from '@/entities/task';
import type { JournalFrame } from './frames';

/**
 * Что устарело от этой записи.
 *
 * Кадр в кэш не пишется: интерфейс не вычисляет за бэкенд (`CONCEPT.md`, 6). Признаки
 * задачи, счётчик вопросов и состав выдачи считаются на сервере из дела и связей —
 * дописать их «по кадру» значит однажды показать не то, что там на самом деле.
 *
 * Ключи заданы префиксами: `['task', 'DEMO-6']` накрывает и пакет карточки, и ленту
 * дела, и прочитанные тела записей этой задачи.
 */
export function keysToInvalidate(frame: JournalFrame): QueryKey[] {
  const keys: QueryKey[] = [
    // Любая запись меняет `updated_at` задачи, а часто и её признаки: список и доска
    // устаревают от чего угодно.
    taskKeys.all,
    ['task', frame.taskKey],
  ];

  // Вопрос и ответ меняют «входящую» и счётчик в шапке.
  if (frame.type === 'question' || frame.type === 'answer') {
    keys.push(questionKeys.all, sessionKeys.bootstrap);
  }

  return keys;
}
