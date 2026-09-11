import type { components } from '@/shared/api';

type EntryType = components['schemas']['EntryType'];
type RemarkOutcome = components['schemas']['RemarkOutcome'];

/**
 * Подписи кирпичей интерфейса: то, что говорит не экран, а сам механизм, — и потому
 * не принадлежит ни одному экрану.
 *
 * Набор ключей обязан совпадать с английским (`dictionaries.test.ts`); форм
 * множественного числа у русского четыре против английских двух, и это расхождением
 * не считается.
 */
export const ui = {
  language: 'Язык интерфейса',
  error: {
    unknown: 'Неизвестная ошибка.',
    unknownCode: 'Неизвестная ошибка ({{code}}).',
    withCode: '{{message}} ({{code}})',
  },

  /**
   * Время для человека. Обо всём остальном во времени говорит `Intl` на языке
   * интерфейса (`shared/lib/locale/time.ts`); словами сказана одна ступень — та, которой
   * в `Intl.RelativeTimeFormat` нет вовсе.
   */
  time: {
    justNow: 'только что',
  },

  /** Оболочка: боковая панель, верхняя полоса, границы ошибок и несуществующий адрес. */
  app: {
    mark: 'C',
    name: 'Casefile',
    sections: 'Разделы',
    trackerSections: 'Разделы Casefile',
    closeSections: 'Закрыть разделы',
    showSections_zero: 'Показать разделы',
    showSections_one: 'Показать разделы, вас ждёт {{count, number}} вопрос',
    showSections_few: 'Показать разделы, вас ждут {{count, number}} вопроса',
    showSections_many: 'Показать разделы, вас ждёт {{count, number}} вопросов',
    showSections_other: 'Показать разделы, вас ждёт {{count, number}} вопроса',
    queues: 'Очереди',
    allTasks: 'Все задачи',
    mine: 'Мне',
    inbox: 'Входящая',
    openQuestions_zero: 'Открытых вопросов нет',
    openQuestions_one: '{{count, number}} открытый вопрос',
    openQuestions_few: '{{count, number}} открытых вопроса',
    openQuestions_many: '{{count, number}} открытых вопросов',
    openQuestions_other: '{{count, number}} открытых вопроса',
    loadingParticipant: 'Загружаем участника…',
    noParticipant: 'участника нет',
    signOut: 'Выйти',
    whereAmI: 'Где я',
    crumbTasks: 'Задачи',
    crumbCase: 'Дело',
    broken: {
      title: 'Интерфейс сломался на этом месте',
      text: 'Экран не отрисовался из-за ошибки в самом интерфейсе — данные тут ни при чём. Подробности ошибки лежат в консоли браузера.',
      reload: 'Перезагрузить',
    },
    notFound: {
      title: 'Страница не найдена',
      text: 'Такого адреса в интерфейсе нет.',
    },
  },

  /** Состояние запроса вместо данных (`shared/ui`, `QueryState`). */
  query: {
    retry: 'Повторить',
    retrying: 'Повторяем…',
  },

  /** Форма записи в дело и подтверждение под ней (`shared/ui`). */
  composer: {
    preview: 'Предпросмотр',
    hidePreview: 'Скрыть предпросмотр',
    agentView: 'Как это увидит агент',
  },
  receipt: {
    close: 'Закрыть',
  },

  /** Представление задачи: строка списка, карточка доски, знаки и навигация. */
  task: {
    columns: {
      key: 'Ключ',
      title: 'Название',
      status: 'Статус',
      assignee: 'Исполнитель',
      priority: 'Приоритет',
      features: 'Признаки',
      activity: 'Активность',
    },
    statusLabel: 'статус',
    priorityLabel: 'приоритет',
    emptyCase: 'в деле пусто',
    cardUnassigned: 'не назначена',
    features: {
      blocked: 'заблокирована: есть связь blocked_by на незакрытую задачу',
      questions_one: '{{count, number}} вопрос без ответа',
      questions_few: '{{count, number}} вопроса без ответа',
      questions_many: '{{count, number}} вопросов без ответа',
      questions_other: '{{count, number}} вопроса без ответа',
      questionsBlocking_one: '{{count, number}} вопрос без ответа, {{blocking}}',
      questionsBlocking_few: '{{count, number}} вопроса без ответа, {{blocking}}',
      questionsBlocking_many: '{{count, number}} вопросов без ответа, {{blocking}}',
      questionsBlocking_other: '{{count, number}} вопроса без ответа, {{blocking}}',
      blockingOf_one: 'из них {{count, number}} блокирующий',
      blockingOf_few: 'из них {{count, number}} блокирующих',
      blockingOf_many: 'из них {{count, number}} блокирующих',
      blockingOf_other: 'из них {{count, number}} блокирующих',
      remarks_one: '{{count, number}} замечание без разбора',
      remarks_few: '{{count, number}} замечания без разбора',
      remarks_many: '{{count, number}} замечаний без разбора',
      remarks_other: '{{count, number}} замечания без разбора',
    },
    nav: {
      label: 'Навигация по задаче {{key}}',
      backAll: '← Ко всем задачам',
      backFiltered: '← К списку с отбором',
      card: 'Карточка',
      case: 'Дело',
    },
  },

  /** Представление записи дела: род, заголовок по фактам и тело. */
  entry: {
    tracker: 'трекер',
    type: {
      summary: 'сводка',
      decision: 'решение',
      attempt: 'попытка',
      finding: 'находка',
      artifact: 'артефакт',
      question: 'вопрос',
      answer: 'ответ',
      verdict: 'вердикт',
      remark: 'замечание',
      resolution: 'резолюция',
      note: 'заметка',
      created: 'заведение',
      status_changed: 'смена статуса',
      section_changed: 'правка раздела',
      field_changed: 'правка поля',
      assignee_changed: 'смена исполнителя',
      link_added: 'связь добавлена',
      link_removed: 'связь снята',
    } satisfies Record<EntryType, string>,
    remarkOutcome: {
      fixed: 'поправлено',
      accepted: 'принято в работу',
      needs_detail: 'нужно уточнение',
      declined: 'менять не будем',
    } satisfies Record<RemarkOutcome, string>,
    headline: {
      created: 'Задача заведена',
      status: 'Статус',
      withReason: '· с причиной',
      sectionEdited: 'Правка раздела',
      fieldEdited: 'Правка поля',
      assignee: 'Исполнитель',
      linkAdded: 'Связь',
      linkRemoved: 'Связь снята',
      answerTo: 'Ответ на',
      check: 'Обзорная проверка {{no}}',
      resolution: 'Разбор',
      resolutionOutcome: '· {{outcome}}',
      none: 'не назначен',
      cleared: 'снят',
    },
    summary: {
      done: 'Сделано',
      remaining: 'Осталось',
      blockers: 'Что мешает',
      nextStep: 'Следующий шаг',
    },
    addressees: 'Кому:',
    blocking: 'блокирующий',
    was: 'Было',
    now: 'Стало',
    noBody: 'Тела у этой записи нет.',
    refs: 'Указатели:',
    emptyValue: 'пусто',
    copy: 'Скопировать {{reference}}',
    copied: 'скопировано',
    clipboardUnavailable: 'буфер обмена недоступен',
  },

  /** Живой поток: состояние связи, полоса обновлений и уведомление о вопросе. */
  live: {
    connecting: 'подключаемся',
    connectingTitle: 'Открываем живой поток журнала',
    online: 'на связи',
    onlineTitle: 'Живой поток журнала открыт: экран обновляется сам',
    offline: 'нет связи',
    offlineTitle: 'Соединение с потоком журнала потеряно, идёт переподключение',
    updates: 'Обновления списка',
    changed_one: 'Изменилась {{count, number}} задача',
    changed_few: 'Изменилось {{count, number}} задачи',
    changed_many: 'Изменилось {{count, number}} задач',
    changed_other: 'Изменилось {{count, number}} задачи',
    changedUnknown: 'Пока не было связи, список мог измениться',
    show: 'Показать',
    questionsToMe: 'Вопросы ко мне',
    blockingBadge: 'блокирующий',
    blockingTitle: 'Работа по задаче стоит без ответа',
    dismiss: 'Закрыть уведомление о вопросе {{reference}}',
  },

  /** Ответ на вопрос: форма живёт и на карточке задачи, и во входящей. */
  answer: {
    formLabel: 'Ответ на {{reference}}',
    fieldLabel: 'Ответ',
    submit: 'Ответить',
    pending: 'Отправляем…',
    open: 'Ответить',
    empty: 'Пустой ответ отправить нельзя: агенту нужен текст, а не факт нажатия кнопки.',
    placeholder: 'Markdown. Ссылки вида DEMO-2 и DEMO-2#7 станут ссылками.',
    retrySafe: 'Повторная отправка не заведёт второй ответ: ключ повтора у попытки тот же.',
    receiptLabel: 'Ответ на {{reference}} подшит',
    receiptHeadline: 'Ответ подшит',
  },

  /** Замечание к задаче: «вышло не то» о задаче целиком. */
  remark: {
    formLabel: 'Замечание к {{key}}',
    fieldLabel: 'Замечание',
    submit: 'Оставить замечание',
    pending: 'Отправляем…',
    empty: 'Пустое замечание отправить нельзя: агенту нужно знать, что именно не так.',
    placeholder: 'Что вышло не так. Markdown; ссылки вида DEMO-2 и DEMO-2#7 станут ссылками.',
    retrySafe: 'Повторная отправка не заведёт второе замечание: ключ повтора у попытки тот же.',
    receiptLabel: 'Замечание к {{key}} подшито',
    receiptHeadline: 'Замечание подшито',
  },
} as const;
