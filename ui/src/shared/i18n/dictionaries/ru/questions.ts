/** Экран входящей: вопросы ко мне и мои замечания без разбора (`src/pages/questions`). */
export const questions = {
  intro: 'Вопросы, которых агенты ждут от вас, и ваши замечания, которых ждёте вы.',
  filterLabel: 'Отбор входящей',
  queue: 'Очередь',
  allQueues: 'все очереди',
  queueNote: 'Очередь отбирает обе половины входящей.',

  questionsTitle: 'Вопросы ко мне',
  blockingOnly: 'только блокирующие',
  loadingQuestions: 'Читаем входящую…',
  noQuestions: 'Вопросов без ответа нет: агенты вас не ждут.',
  questionLabel: 'Вопрос {{reference}}',
  blockingQuestionLabel: 'Блокирующий вопрос {{reference}}',

  remarksTitle: 'Мои замечания без разбора',
  loadingRemarks: 'Читаем замечания…',
  noRemarks: 'Неразобранных замечаний нет.',
  awaitingResolution: 'ждёт разбора',

  more: 'Ещё',
  loadingMore: 'Читаем…',

  emptyByFilter: 'По этому отбору ({{conditions}}) ничего не нашлось.',
  resetFilter: 'Сбросить отбор',
  condition: {
    queue: 'очередь {{queue}}',
    blocking: 'только блокирующие',
  },
} as const;
