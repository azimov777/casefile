# Справочник кодов ошибок

<!--
Файл создаётся командой, править руками нельзя:

    docker compose run --rm schema

Источник — классы исключений в коде (`app/api/contract.py`, `error_catalog`).
Расхождение файла с кодом ловит `tests/test_api_contract.py`.
-->

Любая ошибка приходит одной оболочкой, независимо от эндпоинта:

```json
{"error": {"code": "issue_not_found",
           "message": "Issue TRK-123 not found",
           "details": {}}}
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
| `permission_denied` | Action is not allowed | Действие запрещено. В v1 ролей нет, но точка отказа существует с самого начала. |

## 404 — не найдено

| Код | Сообщение | Когда возникает |
|---|---|---|
| `entry_not_found` | Case entry not found | Записи с таким номером в этой задаче нет. |
| `link_not_found` | Link not found | Связи такого вида между этими задачами нет. |
| `not_found` | Object not found | Запрошенного объекта не существует. |
| `participant_not_found` | Participant not found | Участника с таким именем или идентификатором нет. |
| `queue_not_found` | Queue not found | Очереди с таким ключом нет. |
| `task_not_found` | Task not found | Задачи с таким ключом нет. |
| `token_not_found` | Token not found | Токена с таким идентификатором нет. |

## 405 — метод не поддержан

| Код | Сообщение | Когда возникает |
|---|---|---|
| `method_not_allowed` | Method not allowed | Маршрут есть, но этого метода у него нет. |

## 409 — конфликт состояния

| Код | Сообщение | Когда возникает |
|---|---|---|
| `checks_not_passed` | Some review checks have no passing verdict | `review → done` требует, чтобы последний вердикт каждой проверки был `passed`. |
| `conflict` | State conflict | Состояние объекта не позволяет выполнить операцию: дубликат ключа, гонка версий. |
| `link_cycle_detected` | Link would create a cycle | Связь замкнула бы кольцо в иерархии или в блокировках. |
| `link_exists` | Link already exists | Такая связь между этими задачами уже есть. |
| `participant_name_taken` | Participant name is already taken | Имя участника уже занято: имена уникальны без учёта регистра. |
| `queue_key_taken` | Queue key is already taken | Ключ очереди уже занят: ключи уникальны без учёта регистра. |
| `summary_required` | Transition out of in_progress requires a summary | Выход из `in_progress` требует сводки, подшитой после последнего входа в него. |
| `task_blocked` | Task has an open blocker | Вход в `in_progress` при незакрытом блокере: ключи блокеров в `details.blockers`. |
| `task_closed` | Task is closed | Задача в `done` или `cancelled`: поля и связи закрытой задачи не меняются. |
| `task_field_locked` | Field cannot be changed in the current status | Поле не редактируется в этом статусе: содержание задачи меняется только в `backlog`. |
| `task_has_unclosed_children` | Task has children that are not closed | Переход в `done` при детях не в `done` и не в `cancelled`. |
| `transition_not_allowed` | Transition is not allowed | Перехода между этими статусами нет в таблице; допустимые перечислены в `details.allowed`. |
| `version_conflict` | Task version is outdated | Версия задачи разошлась: её изменили между чтением и записью. |

## 422 — не прошло проверку

| Код | Сообщение | Когда возникает |
|---|---|---|
| `actor_not_addressable` | A temporary agent cannot be an addressee; pass an explicit addressee | Временный агент спрашивает свои вопросы, а адресовать его нельзя. |
| `entry_fields_invalid` | Case entry fields are invalid | Запись не проходит проверку формы; все замечания сразу — в `details.fields`. |
| `invalid_actor_label` | Actor label is invalid | Метка временного агента не соответствует шаблону. |
| `invalid_cursor` | Pagination cursor is malformed | Курсор не разбирается. Ошибка механизма, а не предметной области, поэтому живёт здесь. |
| `invalid_link_kind` | Link kind is invalid | Такого вида связи нет; допустимые перечислены в `details.allowed`. |
| `invalid_page_size` | Page size is out of range | Запрошен размер страницы вне допустимых границ. |
| `invalid_participant_name` | Participant name is invalid | Имя участника не соответствует шаблону. |
| `invalid_queue_key` | Queue key is invalid | Ключ очереди не соответствует шаблону. |
| `invalid_task_key` | Task key is invalid | Ключ задачи не разбирается как `КЛЮЧ-НОМЕР`. |
| `link_self_not_allowed` | A task cannot be linked to itself | Связь задачи с самой собой запрещена — любого вида, включая `relates`. |
| `task_fields_invalid` | Task fields are invalid | Одно или несколько полей задачи не проходят проверку; все замечания в `details.fields`. |
| `task_sections_incomplete` | Task sections are incomplete | Перед `open` четыре раздела должны быть заполнены, а `checks` — не пуст. |
| `transition_reason_required` | Transition requires a reason | Шаг назад по цепочке статусов и отмена требуют причины `reason`. |
| `validation_error` | Validation failed | Входные данные синтаксически корректны, но нарушают правило предметной области. |

## 429 — слишком часто

| Код | Сообщение | Когда возникает |
|---|---|---|
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
