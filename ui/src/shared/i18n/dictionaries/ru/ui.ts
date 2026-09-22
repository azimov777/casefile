import type { components } from '@/shared/api';

type EntryType = components['schemas']['EntryType'];
type RemarkOutcome = components['schemas']['RemarkOutcome'];
type LinkKind = components['schemas']['LinkKind'];

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
    installation: 'Установка',
    connect: 'Подключить агента',
    access: 'Доступы',
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
  copyBlock: {
    action: 'Копировать',
    copied: 'Скопировано',
    label: 'Копировать: {{label}}',
    copiedLabel: 'Скопировано: {{label}}',
    done: '{{label}} — в буфере обмена',
    failed: 'Браузер не дал доступа к буферу обмена: выделите текст и скопируйте его вручную.',
  },

  /** Представление доступа: строка списка на экране «Доступы» (`entities/token`). */
  token: {
    label: 'Доступ «{{name}}»',
    scopeKind: 'набор',
    scopeTask: 'Рабочий цикл агента: задачи, записи дела и чтение всего.',
    scopeMain: 'Рабочий цикл плюс запись реестров: участники, токены и очереди.',
    thisSession: 'ключ этого сеанса',
    revoked: 'отозван',
    shared: 'общий агентский токен',
    issuedBy: 'выпустил {{author}},',
    issuedByTracker: 'выпустила сама установка,',
    lastUsed: 'последний раз ходили',
    neverUsed: 'им ещё не ходили',
    revokedAt: 'отзыв:',
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
    // Родитель задачи подписью на карточке доски и в строке списка (UI-119).
    parents: {
      // Род ссылки для программы чтения с экрана: без него она прочла бы ключ чужой
      // задачи сразу перед ключом своей, не сказав, чья это задача.
      label: 'родитель',
      // Видимая подпись: ключ моноширинным, название как написал агент.
      caption: '<key>{{key}}</key> · {{title}}',
      // Строка подсказки: по родителю на строку.
      item: '{{key}} · {{title}}',
      // Родителей больше одного: число остальных рядом с первым.
      more: '+{{count, number}}',
      others_one: 'и ещё {{count, number}} родитель: {{parents, list}}',
      others_few: 'и ещё {{count, number}} родителя: {{parents, list}}',
      others_many: 'и ещё {{count, number}} родителей: {{parents, list}}',
      others_other: 'и ещё {{count, number}} родителя: {{parents, list}}',
    },
    // Заголовок группы связей одного вида (UI-125): подпись рядом с идентификатором
    // контракта, а не вместо него — сам идентификатор `LinkKindMark` не переводит.
    links: {
      kind: {
        blocked_by: 'Блокируется',
        blocks: 'Блокирует',
        parent: 'Родитель',
        child: 'Дети',
        relates: 'Связано',
      } satisfies Record<LinkKind, string>,
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
      unmeasured: 'Чего проверки не измерили',
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

  /** Фрагменты подключения агента к MCP (`features/connect-agent`). */
  snippets: {
    clients: {
      any: 'Любой клиент MCP',
      claudeCode: 'Claude Code',
      codex: 'Codex',
      json: 'JSON mcpServers',
    },
    labelHint:
      'Общий агентский токен никого не называет, поэтому каждый запрос с ним несёт заголовок <code>{{header}}</code> — подпись временного агента в записях дела. Замените <code>{{placeholder}}</code> меткой латиницей в snake_case, например <code>nightly_agent</code>.',
    anyHint:
      'Транспорт — streamable HTTP. Адрес задаёт установка, заголовки идут с каждым запросом.',
    addressLabel: 'Адрес MCP',
    addressCaption: 'URL',
    headersLabel: 'Заголовки запроса',
    headersCaption: 'Заголовки HTTP',
    claudeHint:
      'Регистрирует сервер <code>{{server}}</code> для всех ваших проектов (<code>--scope user</code>). Работающая сессия новый сервер сама не подхватит: <code>/mcp</code> или перезапуск. Подключился ли он, покажет <code>claude mcp list</code>.',
    claudeLabel: 'Команда Claude Code',
    terminalCaption: 'Терминал',
    codexHint:
      'Токен идёт через переменную окружения <code>{{env}}</code>, и секрет не ложится в файл конфигурации. Codex читает переменную из своего окружения: задайте её там, откуда Codex запускается, а приложение Codex после смены перезапустите.',
    codexFileLabel: 'Секция конфигурации Codex',
    codexEnvBashLabel: 'Переменная с токеном для Codex (bash/zsh)',
    codexEnvBashCaption: 'Терминал, до запуска Codex',
    codexEnvPowerShellLabel: 'Переменная с токеном для Codex (PowerShell)',
    codexEnvPowerShellCaption: 'PowerShell, до запуска Codex',
    codexFormHint:
      'Или те же значения формой в приложении Codex (MCP-серверы в настройках, сервер Streamable HTTP):',
    // Подписи полей — как их показывает приложение Codex на русском (снимок владельца
    // из контекста UI-105); ключ файла стоит рядом, по нему поле и сверяется.
    codexField: {
      url: 'URL',
      bearer_token_env_var: 'Переменная окружения токена Bearer',
      http_headers: 'Заголовки',
    },
    jsonHint:
      'Форма файла <code>.mcp.json</code> Claude Code. У Cursor те же <code>url</code> и <code>headers</code>; Windsurf, Gemini CLI и VS Code называют поля иначе — сверьтесь с документацией своего клиента.',
    jsonLabel: 'Конфигурация mcpServers',
    jsonCaption: 'JSON',
  },
} as const;
