import type { components } from '@/shared/api';

type AnswerOutcome = components['schemas']['AnswerOutcome'];

/** Экран входящей: вопросы ко мне, мои замечания без разбора и история вопросов (`src/pages/questions`). */
export const questions = {
  /** Пояснение экрана (`features/manage-onboarding`, `ExplanationPanel`, `TRK-362`). */
  explanation: {
    body: 'Сюда приходят вопросы, которые агенты задали вам. Пока блокирующий вопрос без ответа, работа по задаче стоит; ваш ответ подшивается в её дело, и агент читает его оттуда, когда продолжает работу. Если агент уже остановился, напишите ему в его чате, что ответили.',
  },
  intro:
    'Задачи, закрытые не целиком, вопросы, которых агенты ждут от вас, и ваши замечания, которых ждёте вы.',
  filterLabel: 'Отбор входящей',
  project: 'Проект',
  allProjects: 'все проекты',
  projectNote: 'Проект отбирает все части входящей.',

  questionsTitle: 'Вопросы ко мне',
  blockingOnly: 'только блокирующие',
  loadingQuestions: 'Читаем входящую…',
  noQuestions: 'Вопросов без ответа нет: агенты вас не ждут.',
  questionLabel: 'Вопрос {{reference}}',
  blockingQuestionLabel: 'Блокирующий вопрос {{reference}}',

  attentionTitle: 'Требуют внимания',
  attentionIntro:
    'Задачи, которые агент закрыл не целиком: проверка прошла частично или её невозможно было выполнить. Откройте задачу и примите недостаток или верните её на доработку.',
  loadingAttention: 'Читаем задачи, закрытые не целиком…',
  noAttention: 'Задач, закрытых не целиком и ждущих решения, нет.',
  attentionLabel: 'Задача {{key}} закрыта не целиком',
  awaitingDecision: 'ждёт решения',

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
  /**
   * Чем закрыт вопрос в истории — исход первого ответа (TRK-552): ответили, сняли как
   * устаревший или заменили другим вопросом.
   */
  closedAs: {
    answered: 'отвечен',
    withdrawn: 'снят',
    replaced: 'заменён',
  } satisfies Record<AnswerOutcome, string>,
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
