import type { components } from '@/shared/api';

type EntryType = components['schemas']['EntryType'];
type RemarkOutcome = components['schemas']['RemarkOutcome'];
type IncompleteOutcome = Extract<
  components['schemas']['VerdictOutcome'],
  'partial' | 'unverifiable'
>;
type LinkKind = components['schemas']['LinkKind'];
/** Виды иерархии: у них заголовок записи о связи называет роль второй задачи словами. */
type HierarchyKind = Extract<LinkKind, 'parent' | 'child'>;
type AuthorKind = components['schemas']['AuthorKind'];

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
  /**
   * Род участника словом (UI-140): значение контракта (`agent`, `human`), но стоит оно
   * подписью рядом с именем, а не идентификатором, — как тип записи и вид связи.
   */
  participantKind: {
    agent: 'агент',
    human: 'человек',
    tracker: 'трекер',
  } satisfies Record<AuthorKind, string>,
  error: {
    unknown: 'Неизвестная ошибка.',
    unknownCode: 'Неизвестная ошибка ({{code}}).',
    withCode: '{{message}} ({{code}})',
    // Причина у поля (`details.fields[].reason`), которой нет в словаре `fieldReasons`
    // (`shared/i18n/dictionaries`): он не обязан покрывать причины целиком.
    unknownFieldReason: 'Значение не подходит ({{reason}}).',
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
    projects: 'Проекты',
    allTasks: 'Все задачи',
    aboutProject: 'О проекте {{key}}',
    showArchived: 'Архивные проекты',
    archivedMark: 'в архиве',
    mine: 'Мне',
    // Первый пункт «Мне»: знакомство с продуктом (TRK-361), а не работа в проекте.
    start: 'Начало',
    // Подпись метки у пункта «Начало» для диктора (TRK-415).
    startUnfinished: 'Знакомство не пройдено',
    inbox: 'Входящая',
    installation: 'Установка',
    connect: 'Подключить агента',
    access: 'Доступы',
    // Перенос — тоже действие над установкой целиком, и тоже только администратору
    // (UI-135), а не работа в проектах.
    moving: 'Перенос установки',
    // Режим входа по учётным записям (`TRK-113`): люди — администратору, учётная
    // запись — каждому вошедшему.
    people: 'Люди',
    account: 'Моя учётная запись',
    openQuestions_zero: 'Открытых вопросов нет',
    openQuestions_one: '{{count, number}} открытый вопрос',
    openQuestions_few: '{{count, number}} открытых вопроса',
    openQuestions_many: '{{count, number}} открытых вопросов',
    openQuestions_other: '{{count, number}} открытых вопроса',
    openWarnings_one: '{{count, number}} задача закрыта не целиком',
    openWarnings_few: '{{count, number}} задачи закрыты не целиком',
    openWarnings_many: '{{count, number}} задач закрыты не целиком',
    openWarnings_other: '{{count, number}} задачи закрыты не целиком',
    loadingParticipant: 'Загружаем участника…',
    noParticipant: 'участника нет',
    signOut: 'Выйти',
    whereAmI: 'Где я',
    crumbTasks: 'Задачи',
    crumbCase: 'Дело',
    crumbProject: 'Проект',
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
    cancel: 'Отмена',
    close: 'Закрыть',
    discardTitle: 'Выбросить черновик?',
    discardDescription: 'Написанное исчезнет и не восстановится.',
    discardConfirm: 'Выбросить',
    keepWriting: 'Продолжить писать',
  },
  receipt: {
    close: 'Закрыть',
  },

  /**
   * Механизм пояснений экрана (`features/manage-onboarding`, `TRK-360#16`, `TRK-362`):
   * подписи самой панели и возврата, общие для любого экрана. Текст пояснения — у
   * экрана, в его собственном пространстве словаря.
   */
  explanation: {
    close: 'Закрыть пояснение',
    hideAll: 'Скрыть все пояснения',
    showAgain: 'Показать пояснения снова',
  },
  /** Проход по экранам (`features/manage-onboarding`, TRK-364): полоса над пояснением и кнопка на «Начало». */
  walk: {
    label: 'Проход по экранам',
    start: 'Пройти по экранам',
    counter: 'Шаг {{n}} из {{total}}',
    back: 'Назад',
    next: 'Далее',
    finish: 'Закончить',
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
  /** Представление учётной записи человека (`entities/account`): карточка в списке людей. */
  account: {
    label: 'Учётная запись {{email}}',
    admin: 'администратор',
    you: 'вы',
    disabled: 'отключена',
    signs: 'подписывается как',
    createdBy: 'завёл {{author}}',
    createdByTracker: 'заведена самой установкой',
    noPassword: 'пароля пока нет',
    disabledAt: 'вход закрыт',
  },

  token: {
    label: 'Доступ «{{name}}»',
    kind: {
      session: 'вход',
      key: 'ключ агента',
      oauth: 'подключение',
    },
    thisSession: 'ключ этого сеанса',
    thisComputer: 'этот компьютер',
    revoked: 'отозван',
    shared: 'общий агентский токен',
    grantedBy: 'кто выдал: {{author}}',
    connectedBy: 'кто подключил: {{author}}',
    byTracker: 'установка',
    signedIn: 'вошли',
    connectedAt: 'вошёл',
    issuedAt: 'выдан',
    lastUsed: 'последний раз ходили',
    lastCall: 'последний вызов',
    neverUsed: 'им ещё не ходили',
    neverCalled: 'вызовов ещё не было',
    revokedAt: 'отзыв:',
    expiresAt: 'сеанс закончится',
    tokenExpires: 'срок токена',
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
      warning: 'закрыта не целиком: ждёт решения — принять или вернуть',
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
      // Плашка родителя в строке таблицы (UI-152): слово, а не одна стрелка, — иначе
      // не сказано, в какую сторону связь.
      badge: 'родитель',
      // Заголовок панели плашки: называет задачу строки, чей это родитель.
      heading: 'Родитель задачи <key>{{key}}</key>',
    },
    // Заголовок группы связей одного вида (UI-125): кем задачи группы приходятся
    // открытой задаче, её глазами (UI-166, UI-168). Идентификатора вида рядом больше
    // нет (владелец, UI-168#10): `parent` называет роль этой задачи, а подпись — роль
    // перечисленных, и пара «parent — Дочерние задачи» читалась противоречием. Прежние
    // «Блокируется»/«Блокирует» не говорили, кто кого держит, — теперь подпись
    // называет открытую задачу («эту задачу» / «эта задача»).
    links: {
      kind: {
        blocked_by: 'Блокирует эту задачу',
        blocks: 'Эта задача блокирует',
        parent: 'Дочерние задачи',
        child: 'Родитель',
        relates: 'Связанные',
      } satisfies Record<LinkKind, string>,
    },
    nav: {
      label: 'Навигация по задаче {{key}}',
      view: 'Вид задачи',
      backAll: '← Ко всем задачам',
      backFiltered: '← К списку с отбором',
      card: 'Карточка',
      case: 'Дело',
    },
  },

  /** Представление записи дела: род, заголовок по фактам и тело. */
  // Опись дела — задачи и проекта одним компонентом (`entities/entry`, `EntryIndex`, UI-174).
  index: {
    empty: 'Дело пусто: записей ещё нет.',
    count_one: 'В деле {{count, number}} запись',
    count_few: 'В деле {{count, number}} записи',
    count_many: 'В деле {{count, number}} записей',
    count_other: 'В деле {{count, number}} записи',
    loadingEntry: 'Читаем запись…',
    columns: {
      no: '№',
      type: 'Тип',
      author: 'Автор',
      when: 'Когда',
      headline: 'Заголовок',
    },
  },
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
      acceptance: 'принятие',
      note: 'заметка',
      created: 'заведение',
      status_changed: 'смена статуса',
      section_changed: 'правка раздела',
      field_changed: 'правка поля',
      assignee_changed: 'смена исполнителя',
      link_added: 'связь добавлена',
      link_removed: 'связь снята',
      moved: 'перенос в другой проект',
      warning: 'предупреждение',
      attribute_created: 'атрибут заведён',
      attribute_changed: 'правка атрибута',
      attribute_removed: 'атрибут снят',
      archived: 'архивирование',
      restored: 'восстановление',
    } satisfies Record<EntryType, string>,
    remarkOutcome: {
      fixed: 'поправлено',
      accepted: 'принято в работу',
      needs_detail: 'нужно уточнение',
      declined: 'менять не будем',
    } satisfies Record<RemarkOutcome, string>,
    // Исходы проверки «не целиком» (TRK-561) — словами: на них реагирует человек.
    // `passed` и `failed` остаются идентификаторами, как были.
    verdictOutcome: {
      partial: 'частично',
      unverifiable: 'невозможно проверить',
    } satisfies Record<IncompleteOutcome, string>,
    headline: {
      created: 'Задача заведена',
      projectCreated: 'Проект заведён',
      status: 'Статус',
      withReason: '· с причиной',
      sectionEdited: 'Правка раздела',
      sectionsEdited: 'Правка разделов',
      fieldEdited: 'Правка поля',
      assignee: 'Исполнитель',
      linkAdded: 'Связь',
      linkRemoved: 'Связь снята',
      moved: 'Перенос',
      attributeCreated: 'Атрибут заведён',
      attributeChanged: 'Правка атрибута',
      attributeRemoved: 'Атрибут снят',
      projectArchived: 'Проект в архиве',
      projectRestored: 'Проект восстановлен',
      // Кем вторая задача приходится этой (UI-166). Только у `parent`/`child`: их
      // идентификатор, прочитанный фразой («parent DEMO-9»), называет роль наоборот —
      // у `blocks DEMO-3` и `relates DEMO-3` фраза читается верно и без слов.
      linkRole: {
        parent: '— дочерняя задача',
        child: '— родитель',
      } satisfies Record<HierarchyKind, string>,
      answerTo: 'Ответ на',
      // Снятие и замена вопроса (TRK-552): «Вопрос KEY#N снят», «Вопрос KEY#N заменён
      // вопросом KEY#M» — называется то, что случилось с вопросом, а не «ответ».
      question: 'Вопрос',
      withdrawn: 'снят',
      replacedBy: 'заменён вопросом',
      check: 'Обзорная проверка {{no}}',
      // Предупреждение закрытия (TRK-561): «Закрыта не целиком: проверка 2 частично».
      warning: 'Закрыта не целиком:',
      warningCheck: 'проверка {{no}}',
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
    copyLink: 'Скопировать ссылку на запись #{{no}}',
    linkCopied: 'Ссылка на запись скопирована',
    group: {
      range: '{{first}}–{{last}}',
      label: 'Записи {{first}}–{{last}}: правка разделов одним действием',
      expand_one: 'Показать {{count, number}} правку',
      expand_few: 'Показать {{count, number}} правки',
      expand_many: 'Показать {{count, number}} правок',
      expand_other: 'Показать {{count, number}} правки',
      collapse: 'Свернуть правки',
    },
  },

  /** Живой поток: состояние связи, полоса обновлений и уведомление о вопросе. */
  live: {
    connecting: 'подключаемся',
    connectingTitle: 'Открываем живой поток журнала',
    online: 'на связи',
    onlineTitle: 'Живой поток журнала открыт: экран обновляется сам',
    offline: 'нет связи',
    offlineTitle: 'Соединение с потоком журнала потеряно, идёт переподключение',
    explain: 'Живой поток: {{state}}. Подробнее',
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

  /** Предупреждение закрытия на карточке задачи (`features/accept-warning`, TRK-561). */
  warning: {
    title: 'Закрыта не целиком',
    text: 'Агент закрыл задачу, но эти проверки прошли не целиком. Примите недостаток или верните задачу на доработку замечанием — его разберёт агент.',
    accept: 'Принять',
    accepting: 'Принимаем…',
    acceptTitle: 'Принято без доработки',
    return: 'Вернуть на доработку',
    closedBy: 'Закрыл задачу:',
  },

  /** Фрагменты подключения агента к MCP (`features/connect-agent`). */
  snippets: {
    clientNav: 'Клиент',
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
      'Плагин несёт скил и подключение к этой установке; вход — OAuth, откроется браузер, ключ не ложится ни в один файл. Работающая сессия нового плагина не увидит: перезапустите её или выполните <code>/reload-plugins</code>. Ключ с этого экрана — для клиентов без OAuth: вкладки «JSON mcpServers» и «Любой клиент MCP».',
    claudeLabel: 'Claude Code: плагин и вход',
    terminalCaption: 'Терминал',
    codexLabel: 'Codex: плагин и вход',
    codexHint:
      'Плагин несёт скил и подключение; вход — OAuth, без ключа. Обновить: <code>codex plugin marketplace upgrade casefile</code>; приложение Codex после установки перезапустите.',
    codexUrlHint:
      'В плагин зашит адрес <code>http://127.0.0.1:8100/mcp</code>. У вашей установки другой: добавьте эти строки в конфигурацию Codex (ключа в них нет) и войдите командой <code>codex mcp login casefile</code>.',
    codexUrlLabel: 'Адрес установки для Codex',
    plainHttpWarning:
      'Этот адрес — обычный http вне этой машины: служба отдаёт вход OAuth только по https, и плагин не подключится. Опубликуйте установку по https или подключайтесь ключом (вкладки «JSON mcpServers» и «Любой клиент MCP»).',
    codexAppHint: 'Или пунктом «Добавить маркетплейс» в приложении Codex:',
    codexAppField: {
      source: 'Источник',
      ref: 'Git ref',
    },
    jsonHint:
      'Форма файла <code>.mcp.json</code> Claude Code. У Cursor те же <code>url</code> и <code>headers</code>; Windsurf, Gemini CLI и VS Code называют поля иначе — сверьтесь с документацией своего клиента.',
    jsonLabel: 'Конфигурация mcpServers',
    jsonCaption: 'JSON',
    skill: {
      title: 'Установите скил',
      intro:
        'Claude Code и Codex получают скил вместе с плагином (вкладки левее). Клиентам без плагина скил ставится отдельно: он учит агента пользоваться инструментами — как вести дело, что записать перед остановкой, что делать при 401. Токен ему не нужен, он один для всех установок. Команды выполняются на машине, где работает агент.',
      otherLabel: 'Установка скила в другого агента',
      machineHint:
        'Или одна строка на машине агента: она ставит скил во все найденные там клиенты и печатает, где он встал (она ставит и плагин Claude Code и Codex, подключённый к этой установке через <code>CASEFILE_URL</code>; без этой переменной плагин получает адрес по умолчанию и приносит только скил). Docker и каталог установки для неё не нужны — переменная <code>CASEFILE_SKILL_ONLY=1</code> оставляет только скил.',
      machineBashLabel: 'Скил во все клиенты машины (bash/zsh)',
      machineBashCaption: 'Терминал, на машине агента',
      machinePowerShellLabel: 'Скил во все клиенты машины (PowerShell)',
      machinePowerShellCaption: 'PowerShell, на машине агента',
    },
  },
  // Плашка внизу боковой панели: вышел выпуск новее установки (TRK-416).
  release: {
    available: 'Доступен выпуск v{{version}}',
    current: 'У вас v{{version}}',
    newTab: '(заметки к выпуску откроются в новой вкладке)',
  },
} as const;
