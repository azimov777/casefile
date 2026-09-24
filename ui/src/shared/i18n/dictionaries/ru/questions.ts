/** Экран входящей: вопросы ко мне, мои замечания без разбора и история вопросов (`src/pages/questions`). */
export const questions = {
  intro: 'Вопросы, которых агенты ждут от вас, и ваши замечания, которых ждёте вы.',
  filterLabel: 'Отбор входящей',
  project: 'Проект',
  allProjects: 'все проекты',
  projectNote: 'Проект отбирает обе половины входящей.',

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

  view: {
    label: 'Вид входящей',
    inbox: 'Ждут ответа',
    history: 'История вопросов',
  },
  historyIntro:
    'Все вопросы вместе с ответами, от свежих к старым. Ответить отсюда нельзя: открытые вопросы ждут во входящей.',
  historyFilterLabel: 'Отбор истории',
  onlyMine: 'только адресованные мне',
  historyTitle: 'Вопросы и ответы',
  loadingHistory: 'Читаем историю вопросов…',
  noHistory: 'Вам ещё не задавали вопросов.',
  noHistoryAnyone: 'Вопросов ещё не задавали.',
  addressees: 'Кому: {{names}}',
  answered: 'отвечен',
  awaitingAnswer: 'ждёт ответа',
  noAnswerYet: 'Ответа пока нет.',
  answersLabel: 'Ответы на {{reference}}',
  answerLabel: 'Ответ {{reference}}',

  more: 'Ещё',
  loadingMore: 'Читаем…',

  emptyByFilter: 'По этому отбору ({{conditions}}) ничего не нашлось.',
  resetFilter: 'Сбросить отбор',
  condition: {
    project: 'проект {{project}}',
    blocking: 'только блокирующие',
  },
} as const;
