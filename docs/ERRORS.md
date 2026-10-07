# Справочник кодов ошибок

<!--
Файл создаётся командой, править руками нельзя:

    docker compose run --rm schema

Источник — классы исключений в коде (`app/api/contract.py`, `error_catalog`).
Расхождение файла с кодом ловит `tests/test_api_contract.py`.
-->

Любая ошибка приходит одной оболочкой, независимо от эндпоинта:

```json
{"error": {"code": "task_not_found",
           "message": "Task not found",
           "details": {"key": "TRK-123"}}}
```

Решения клиент принимает по `code`: он стабилен и меняется только вместе с версией API.
`message` — техническая фраза для разработчика и лога, показывать её пользователю не
нужно; текст интерфейса фронтенд выбирает сам по коду. `details` — структурированные
подробности: какое поле, какое правило, какие значения допустимы.

Коды перечислены по HTTP-статусу, внутри статуса — по алфавиту.

## 400 — запрос не разобран

| Код | Сообщение | Когда возникает |
|---|---|---|
| `bad_request` | Bad request | Запрос синтаксически неверен: тело не разбирается как JSON. |

## 401 — не аутентифицирован

| Код | Сообщение | Когда возникает |
|---|---|---|
| `actor_label_required` | Shared agent token requires the X-Actor-Label header | Общий агентский токен пришёл без метки временного агента. |
| `unauthorized` | Authentication required | Запрос не аутентифицирован: токена нет, он неизвестен или отозван. |

## 403 — запрещено

| Код | Сообщение | Когда возникает |
|---|---|---|
| `admin_required` | Only an administrator can manage accounts | Управление людьми открыто только администратору (`docs/CONCEPT.md`, 5.4). |
| `agent_owned_by_another` | Only an administrator can issue a token to an agent owned by another person | Ключ агента с чужим хозяином выпускает только администратор (TRK-475#14). |
| `human_token_not_allowed` | A key cannot be issued to a person: people sign in, keys are for agents | Ключ человеку не выпускается: человек входит в интерфейс, а не ходит с токеном (TRK-469#25). |
| `permission_denied` | Action is not allowed | Действие запрещено. В v1 ролей нет, но точка отказа существует с самого начала. |

## 404 — не найдено

| Код | Сообщение | Когда возникает |
|---|---|---|
| `account_not_found` | Account not found | Учётной записи с таким идентификатором или почтой нет. |
| `area_not_found` | Area not found | Области с таким адресом нет: проект есть, ключа в нём нет (`CONCEPT.md`, 3.7). |
| `attribute_not_found` | Attribute not found | Атрибута с таким именем (без учёта регистра) у проекта или области нет. |
| `discussion_not_found` | Discussion not found | Обсуждения с таким адресом нет: проект есть, номера в нём нет (решение `TRK#51`). |
| `discussion_task_not_found` | Task is not attached to the discussion | Задача не привязана к этому обсуждению — отвязывать нечего. |
| `entry_not_found` | Case entry not found | Записи с таким номером в этой задаче нет. |
| `link_not_found` | Link not found | Связи такого вида между этими задачами нет. |
| `not_found` | Object not found | Запрошенного объекта не существует. |
| `participant_not_found` | Participant not found | Участника с таким именем или идентификатором нет. |
| `project_not_found` | Project not found | Проекта с таким ключом нет. |
| `task_not_found` | Task not found | Задачи с таким ключом нет. |
| `token_not_found` | Token not found | Токена с таким идентификатором нет. |

## 405 — метод не поддержан

| Код | Сообщение | Когда возникает |
|---|---|---|
| `method_not_allowed` | Method not allowed | Маршрут есть, но этого метода у него нет. |

## 409 — конфликт состояния

| Код | Сообщение | Когда возникает |
|---|---|---|
| `acceptance_by_closer` | The warning cannot be accepted by the signature that closed the task | Предупреждение принимает та же подпись, что закрыла задачу. |
| `account_email_taken` | Account email is already taken | Почта уже занята другой учётной записью: адреса уникальны без учёта регистра. |
| `archive_revision_unknown` | The archive comes from a newer Casefile; update this installation first | Ревизии схемы архива приёмник не знает: архив снят более новым Casefile. |
| `area_archived` | Area is archived: its card, attributes and case are frozen | Область в архиве: карточка, атрибуты и дело заморожены (`CONCEPT.md`, 3.7). |
| `area_key_taken` | Area key is already taken in this project | Ключ области уже занят в этом проекте: ключи уникальны без учёта регистра. |
| `area_not_archived` | Area is not archived | Восстанавливать нечего: область не в архиве. |
| `assignee_mismatch` | Task is assigned to someone else | Вход в `in_progress` не от исполнителя задачи. |
| `assignee_required` | Task has no assignee | Вход в `in_progress` у задачи без исполнителя. |
| `checks_not_passed` | Some checks have no verdict, or a failed one, recorded since the last entry into in_progress | `in_progress → done` требует по каждой проверке вердикта не `failed`, подшитого после последнего входа в `in_progress`. |
| `closing_not_a_transition` | Closing a task is a separate call, not a status transition | `done` достигается только сценарием закрытия, а не переводом статуса. |
| `conflict` | State conflict | Состояние объекта не позволяет выполнить операцию: дубликат ключа, гонка версий. |
| `decision_not_in_force` | Project decision is superseded by a later decision | Решение проекта уже заменено другим, а его называют как действующее. |
| `discussion_closed` | Discussion is closed: its case and its tasks are frozen | Обсуждение закрыто: любая запись, привязка, отвязка и повторное закрытие — отказ. |
| `discussion_has_open_questions` | Discussion has questions with no answer | Закрытие обсуждения, в деле которого есть вопрос без ответа: адреса вопросов (`TRK~7#3`) — в `details.questions`. |
| `discussion_task_exists` | Task is already attached to the discussion | Задача уже привязана к этому обсуждению: привязка хранится одной строкой. |
| `finding_not_in_force` | Project finding is superseded by a later finding | Заметка дела проекта уже заменена другой, а её заменяют снова. |
| `idempotency_key_reused` | Idempotency key was used for a different request | Ключ идемпотентности уже использован другим запросом. |
| `installation_not_empty` | Only an installation without projects can take an archive | Приём архива в установку, где уже есть проекты. |
| `last_admin` | The installation must keep at least one active administrator | Действие оставило бы установку без действующего администратора. |
| `link_cycle_detected` | Link would create a cycle | Связь замкнула бы кольцо в иерархии или в блокировках. |
| `link_exists` | Link already exists | Такая связь между этими задачами уже есть. |
| `participant_has_account` | Participant already has an account | У этого участника учётная запись уже есть: у человека она одна. |
| `participant_name_taken` | Participant name is already taken | Имя участника уже занято: имена уникальны без учёта регистра. |
| `project_archived` | Project is archived: it and its tasks are frozen | Проект в архиве: он и его задачи заморожены для изменений (`CONCEPT.md`, 3.2). |
| `project_key_taken` | Project key is already taken | Ключ проекта уже занят: ключи уникальны без учёта регистра. |
| `project_not_archived` | Project is not archived | Восстанавливать нечего: проект не в архиве. |
| `summary_required` | Transition out of in_progress requires a summary | Выход из `in_progress` требует сводки, подшитой после последнего входа в него. |
| `task_already_in_project` | Task is already in this project | Перенос в проект, где задача уже лежит: переносить некуда (`CONCEPT.md`, 3.3). |
| `task_blocked` | Task has an open blocker | Вход в `in_progress` при незакрытом блокере: ключи блокеров в `details.blockers`. |
| `task_checks_frozen` | Checks cannot be changed after the task has entered in_progress | Проверки задачи, уже входившей в `in_progress`, не правятся. |
| `task_closed` | Task is closed | Задача в `done` или `cancelled`: поля не меняются, и связи, влияющие на переходы, тоже. |
| `task_deferred` | Task is deferred until its not_before moment | Вход в `in_progress` до момента `not_before` по часам базы: момент в `details.not_before`. |
| `task_field_locked` | Field cannot be changed in the current status | Поле не редактируется в этом статусе: содержание задачи меняется только в `backlog`. |
| `task_has_open_blocking_questions` | Task has open blocking questions | Вход в `in_progress` при вопросе без ответа, который держит работу: адреса вопросов в `details.questions` — `TRK-42#3` у вопроса `blocking` в деле задачи, `TRK~7#3` у вопроса в незакрытом обсуждении, к которому задача привязана. |
| `task_has_open_discussions` | Task has discussions that are not closed | Закрытие или отмена задачи, пока привязанное к ней обсуждение не закрыто: адреса обсуждений — в `details.discussions`. |
| `task_has_parent` | Task already has a parent | У задачи уже есть родитель: второй не ставится, нынешний назван в `details.parent`. |
| `task_has_unclosed_children` | Task has children that are not closed | Закрытие задачи при детях не в `done` и не в `cancelled`. |
| `transition_not_allowed` | Transition is not allowed | Перехода между этими статусами нет в таблице; допустимые перечислены в `details.allowed`. |
| `version_conflict` | Task version is outdated | Версия задачи разошлась: её изменили между чтением и записью. |
| `warning_not_open` | Task has no open warning to accept | `acceptance` в задаче, где нечего принимать: открытого предупреждения нет. |

## 422 — не прошло проверку

| Код | Сообщение | Когда возникает |
|---|---|---|
| `account_requires_human` | Only a human participant can have an account | Учётную запись заводят только человеку: агенты ходят токенами, входить им некуда. |
| `actor_not_addressable` | A temporary agent cannot be an addressee; pass an explicit addressee | Временный агент спрашивает свои вопросы, а адресовать его нельзя. |
| `addressee_with_any_addressee` | Questions are filtered either by addressee or by any addressee, not by both | В выдаче вопросов назван адресат и тут же снято условие адресата. |
| `archive_format_unsupported` | This is not an installation archive this Casefile can read | Документ — не архив установки этой раскладки: чужой `format` или `format_version`. |
| `archive_invalid` | The installation archive is malformed | Архив противоречит сам себе или схеме своей ревизии. |
| `area_description_too_long` | Area description is too long | Описание области длиннее предела (`app/domain/areas.py`); не обрезается. |
| `area_project_mismatch` | Area belongs to another project than the task | Область другого проекта: задаче подходит область её собственного проекта. |
| `area_reason_required` | Archiving or restoring an area requires a reason | Архивирование и восстановление области требуют непустой причины `reason`. |
| `attribute_reason_required` | Changing or removing an attribute requires a reason | Изменение и снятие атрибута требуют непустой причины `reason`. |
| `attribute_value_too_long` | Attribute value is too long | Значение атрибута длиннее предела (`app/domain/attributes.py`). |
| `current_password_mismatch` | Current password does not match | Смена своего пароля прислала неверный прежний пароль. |
| `cursor_with_offset` | Page is addressed either by cursor or by offset, not by both | Страница адресована сразу двумя способами: и курсором, и смещением. |
| `entry_fields_invalid` | Case entry fields are invalid | Запись не проходит проверку формы; все замечания сразу — в `details.fields`. Снять (`withdrawn`) или заменить (`replaced`) можно только вопрос, на который ещё не ответили: у отвеченного это `already_answered`. |
| `invalid_actor_label` | Actor label is invalid | Метка временного агента не соответствует шаблону. |
| `invalid_area_key` | Area key is invalid | Адрес новой области не `ПРОЕКТ/ключ` или ключ не по шаблону. |
| `invalid_attribute_name` | Attribute name is invalid | Имя атрибута не соответствует шаблону. |
| `invalid_cursor` | Pagination cursor is malformed | Курсор не разбирается. Ошибка механизма, а не предметной области, поэтому живёт здесь. |
| `invalid_discussion_address` | Discussion address is invalid | Адрес обсуждения не разбирается как `ПРОЕКТ~номер`; форма — в `details.expected`. |
| `invalid_email` | Email is invalid | Почта не похожа на адрес: нет `@`, пустая часть, пробел или слишком длинная. |
| `invalid_idempotency_key` | Idempotency key is invalid | Ключ идемпотентности пуст или длиннее допустимого. |
| `invalid_journal_cursor` | Last-Event-ID is not a journal sequence number | `Last-Event-ID` потока не разбирается как сквозной номер записи. |
| `invalid_link_kind` | Link kind is invalid | Такого вида связи нет; допустимые перечислены в `details.allowed`. |
| `invalid_page_offset` | Page offset is negative | Смещение страницы отрицательное. |
| `invalid_page_size` | Page size is out of range | Запрошен размер страницы вне допустимых границ. |
| `invalid_participant_name` | Participant name is invalid | Имя участника не соответствует шаблону. |
| `invalid_project_key` | Project key is invalid | Ключ проекта не соответствует шаблону. |
| `invalid_search_query` | Search query cannot be parsed | Строка на языке запросов не разбирается. |
| `invalid_task_key` | Task key is invalid | Ключ задачи не разбирается как `КЛЮЧ-НОМЕР`. |
| `journal_too_many_tasks` | Too many tasks in one journal filter | Задач в одном фильтре ленты больше потолка: потолок и присланное — в `details`. |
| `journal_wait_too_long` | Requested wait exceeds the ceiling | Запрошенное ожидание больше потолка: потолок и запрошенное лежат в `details`. |
| `link_self_not_allowed` | A task cannot be linked to itself | Связь задачи с самой собой запрещена — любого вида, включая `relates`. |
| `project_description_too_long` | Project description is too long | Описание проекта длиннее предела (`app/domain/projects.py`). |
| `project_reason_required` | Archiving or restoring a project requires a reason | Архивирование и восстановление проекта требуют непустой причины `reason`. |
| `search_field_unknown` | Search field is unknown | Имени поля отбора или ключа сортировки нет: допустимые перечислены в `details.allowed`. |
| `search_operator_not_supported` | Operator is not supported for this field | Оператор к этому полю неприменим: допустимые перечислены в `details.allowed`. |
| `search_value_invalid` | Search value is invalid | Значение условия не разрешается: нет такого проекта, статуса, не число. |
| `task_fields_invalid` | Task fields are invalid | Одно или несколько полей задачи не проходят проверку; все замечания в `details.fields`. |
| `task_move_batch_size_invalid` | Number of tasks in one move is outside the allowed range | Список ключей переноса пуст или длиннее потолка: границы и присланное — в `details`. |
| `task_move_reason_required` | Moving a task to another project requires a reason | Перенос задачи в другой проект требует непустой причины `reason` (`CONCEPT.md`, 3.3). |
| `task_sections_incomplete` | Task sections are incomplete | Перед `open` четыре раздела должны быть заполнены, а `checks` — не пуст. |
| `transition_reason_required` | Transition requires a reason | Шаг назад по цепочке статусов и отмена требуют причины `reason`. |
| `validation_error` | Validation failed | Входные данные синтаксически корректны, но нарушают правило предметной области. |
| `weak_password` | Password does not meet the rules | Новый пароль не годится: короче минимума или длиннее потолка. |

## 429 — слишком часто

| Код | Сообщение | Когда возникает |
|---|---|---|
| `journal_stream_limit` | Too many open journal streams | Открытых потоков журнала на этом процессе столько, сколько разрешено настройкой. |
| `password_attempts_exceeded` | Too many password attempts | Неудачных попыток входа за окно столько, сколько разрешено: пароль не проверяется. |
| `too_many_requests` | Too many requests | Ресурс исчерпан и просьба повторить позже, а не отказ навсегда. |

## 500 — внутренняя ошибка

| Код | Сообщение | Когда возникает |
|---|---|---|
| `internal_error` | Internal server error | Ошибка приложения, у которой есть стабильный код и HTTP-статус. |

## 503 — сервис недоступен

| Код | Сообщение | Когда возникает |
|---|---|---|
| `database_unavailable` | Database is unavailable | База не отвечает. Отдельный код, чтобы мониторинг отличал это от прочих пятисоток. |

## Любой статус

| Код | Сообщение | Когда возникает |
|---|---|---|
| `http_error` | Request error | Запасной код для статуса, которого нет в таблице соглашений. Появление такого ответа означает пропущенную ветку, а не рабочее состояние. |
