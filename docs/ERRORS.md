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
| `unauthorized` | Authentication required | Запрос не аутентифицирован: токена нет, он неизвестен, отозван или актор отключён. |

## 403 — запрещено

| Код | Сообщение | Когда возникает |
|---|---|---|
| `permission_denied` | Action is not allowed | Действие запрещено. В v1 ролей нет, но точка отказа существует с самого начала. |

## 404 — не найдено

| Код | Сообщение | Когда возникает |
|---|---|---|
| `actor_not_found` | Actor not found | Актора с таким ключом или идентификатором нет. |
| `api_token_not_found` | API token not found | Токена с таким идентификатором у актора нет. |
| `automation_rule_not_found` | Automation rule not found | Правила с таким ключом нет ни в реестре кода, ни в таблице состояния. |
| `board_column_not_found` | Board column not found | Колонки с таким идентификатором у этой доски нет. |
| `board_not_found` | Board not found | Доски с таким идентификатором нет. |
| `checklist_item_not_found` | Checklist item not found | Пункта чеклиста с таким идентификатором у этой задачи нет. |
| `comment_not_found` | Comment not found | Комментария с таким идентификатором у этой задачи нет. |
| `field_not_found` | Field not found | Поля с такой ссылкой нет. |
| `issue_not_found` | Issue not found | Задачи с таким ключом нет. |
| `issue_type_not_found` | Issue type not found | Типа задачи с такой ссылкой нет. |
| `link_not_found` | Issue link not found | Связи с таким идентификатором у этой задачи нет. |
| `not_found` | Object not found | Запрошенного объекта не существует. |
| `notification_not_found` | Notification not found | Уведомления с таким идентификатором в инбоксе этого актора нет. |
| `portfolio_not_found` | Portfolio not found | Портфеля с таким ключом или идентификатором нет. |
| `project_not_found` | Project not found | Проекта с таким ключом или идентификатором нет. |
| `queue_not_found` | Queue not found | Очереди с таким ключом нет. |
| `resolution_not_found` | Resolution not found | Резолюции с такой ссылкой нет. |
| `saved_filter_not_found` | Saved filter not found | Сохранённого фильтра с таким идентификатором нет. |
| `status_not_found` | Status not found | Статуса с такой ссылкой нет. |
| `subscription_not_found` | Notification subscription not found | Подписки с таким идентификатором у этого актора нет. |
| `transition_not_found` | Workflow transition not found | Перехода с таким идентификатором нет в указанном воркфлоу. |
| `webhook_delivery_not_found` | Webhook delivery not found | Записи журнала доставок с таким идентификатором нет. |
| `webhook_subscription_not_found` | Webhook subscription not found | Подписки вебхука с таким идентификатором нет. |
| `workflow_not_found` | Workflow not found | Воркфлоу с таким идентификатором нет. |

## 405 — метод не поддержан

| Код | Сообщение | Когда возникает |
|---|---|---|
| `method_not_allowed` | Method not allowed | Маршрут есть, но этого метода у него нет. |

## 409 — конфликт состояния

| Код | Сообщение | Когда возникает |
|---|---|---|
| `actor_inactive` | Actor is inactive | Актор отключён: выпускать ему токены и действовать от его имени нельзя. |
| `actor_key_taken` | Actor key is already taken | Ключ актора уже занят: ключ уникален на всю установку. |
| `automation_rule_disabled` | Automation rule is disabled | Правило выключено: запускать его вручную нельзя. |
| `automation_rule_kind_mismatch` | This rule kind cannot be run this way | Форма правила не та: вручную запускают макрос, а не триггер и не автодействие. |
| `automation_rule_out_of_scope` | Issue is out of the scope of this rule | Задача не входит в область правила: правило привязано к другой очереди. |
| `automation_rule_unavailable` | Automation rule has no declaration in the code | Состояние правила в базе есть, а объявления в коде — нет. |
| `board_status_taken` | Status already belongs to another column of this board | Статус уже разложен в другую колонку этой доски. |
| `comment_deleted` | Comment is deleted | Комментарий удалён: править и удалять его повторно нечего. |
| `conflict` | State conflict | Состояние объекта не позволяет выполнить операцию: дубликат ключа, гонка версий. |
| `epic_cannot_have_parent` | An epic cannot have a parent issue | У задачи типа «эпик» родителя быть не может. |
| `field_in_use` | Field is in use | Поле используется задачами: жёстко удалить его нельзя, только скрыть. |
| `field_key_taken` | Field key is already taken in this scope | Ключ поля занят в этой области: глобально либо внутри очереди. |
| `field_type_locked` | Field type cannot be changed while the field has values | У поля есть значения: тип и множественность менять нельзя. |
| `issue_not_on_board` | Issue is not in the scope of this board | Задача не попадает в область доски: ранжировать и двигать её здесь нечего. |
| `issue_referenced` | Issue is referenced by other issues | На задачу ссылаются кастомные поля других задач: удалять её нельзя. |
| `issue_type_in_use` | Issue type is in use | Тип задачи используется: есть задачи этого типа или он назначен по умолчанию. |
| `issue_type_key_taken` | Issue type key is already taken in this scope | Ключ типа задачи занят в этой области. |
| `link_already_exists` | Issue link already exists | Такая связь между этими задачами уже есть. |
| `link_cycle_detected` | Issue link would create a hierarchy cycle | Связь замкнула бы иерархию в кольцо. |
| `link_parent_exists` | Issue already has a parent | У задачи уже есть родитель: второго не бывает. |
| `portfolio_archived` | Portfolio is archived | Портфель в архиве: вкладывать в него проекты и портфели нельзя. |
| `portfolio_cycle_detected` | Portfolio nesting would create a cycle | Вложение замкнуло бы кольцо портфелей. |
| `portfolio_key_taken` | Portfolio key is already taken | Ключ портфеля уникален на установку. |
| `project_archived` | Project is archived | Проект в архиве и новых задач не принимает. |
| `project_key_taken` | Project key is already taken | Ключ проекта уникален на установку: по нему адресуют проект и фильтруют задачи. |
| `queue_archived` | Queue is archived | Очередь в архиве: новые задачи в неё не заводятся. |
| `queue_key_taken` | Queue key is already taken | Ключ очереди уже занят: он уникален на всю установку и неизменяем после создания. |
| `queue_not_empty` | Queue still has issues | В очереди есть задачи: удалять её нельзя, для этого есть архивация. |
| `resolution_in_use` | Resolution is in use | Резолюция используется задачами. |
| `resolution_key_taken` | Resolution key is already taken in this scope | Ключ резолюции занят в этой области. |
| `saved_filter_name_taken` | Saved filter name is already taken by this owner | Имя фильтра уникально у владельца: два одноимённых фильтра неразличимы в списке. |
| `status_category_locked` | Status category cannot be changed while issues use the status | Категорию статуса с задачами менять нельзя. |
| `status_in_use` | Status is in use | Статус используется: в нём стоят задачи или он назначен очереди по умолчанию. |
| `status_key_taken` | Status key is already taken in this scope | Ключ статуса занят в этой области: глобально либо внутри очереди. |
| `subscription_exists` | Subscription for this scope already exists | У актора уже есть подписка на эту область в этом канале. |
| `system_actor_protected` | System actor is managed by the application | Системный актор управляется приложением, а не API. |
| `transition_not_allowed` | Workflow transition is not allowed | Текущий воркфлоу не разрешает запрошенную смену статуса. |
| `version_conflict` | Issue was changed by someone else | Версия задачи разошлась: её изменили между чтением и записью. |
| `webhook_delivery_not_retryable` | Webhook delivery is still pending | Переотправлять нечего: доставка ещё в работе. |
| `webhook_subscription_disabled` | Webhook subscription is disabled | Подписка выключена: ставить на неё доставку нельзя. |
| `webhook_subscription_name_taken` | Webhook subscription name is already taken | Имя подписки уже занято. |
| `workflow_assignment_conflict` | Workflow cannot be assigned to this issue type | Воркфлоу нельзя назначить типу, не оставив существующие задачи вне графа. |
| `workflow_in_use` | Workflow is assigned to issue types | Назначенный типам задач воркфлоу нельзя удалить. |
| `workflow_name_taken` | Workflow name is already taken in this queue | Имя воркфлоу уникально внутри очереди. |
| `workflow_status_in_use` | Workflow status is used by issues | Из графа нельзя убрать статус, в котором стоят задачи этого процесса. |

## 422 — не прошло проверку

| Код | Сообщение | Когда возникает |
|---|---|---|
| `automation_params_invalid` | Automation rule parameters are invalid | Параметры правила не прошли проверку его же схемой. |
| `catalog_entry_unavailable` | Catalog entry is not available in this queue | Запись существует, но в этой очереди недоступна. |
| `field_unavailable` | Field is not available here | Поле существует, но в этой очереди или у этого типа задачи неприменимо. |
| `field_values_invalid` | Custom field values failed validation | Значения кастомных полей не прошли проверку. |
| `invalid_actor_key` | Actor key is invalid | Ключ не соответствует шаблону или зарезервирован. |
| `invalid_automation_rule` | Automation rule definition is invalid | Объявление правила или его настройка нарушают правило. |
| `invalid_board` | Board definition is invalid | Описание доски или колонки нарушает правило. |
| `invalid_board_move` | Board move is not well defined | Перемещение карточки описано неоднозначно или неверно. |
| `invalid_catalog_key` | Catalog key is invalid | Ключ записи справочника не соответствует шаблону. |
| `invalid_catalog_ref` | Catalog reference is invalid | Ссылка на запись справочника не разбирается: ожидается `key` или `QUEUE.key`. |
| `invalid_checklist_item` | Checklist item is invalid | Пункт чеклиста нарушает правило: пустой текст, перенос строки, потолок пунктов. |
| `invalid_comment_body` | Comment body is invalid | Текст комментария пуст или длиннее допустимого. |
| `invalid_cursor` | Pagination cursor is malformed | Курсор не разбирается. Ошибка механизма, а не предметной области, поэтому живёт здесь. |
| `invalid_field_definition` | Field definition is invalid | Описание поля противоречит само себе. |
| `invalid_field_key` | Field key is invalid | Ключ поля не соответствует шаблону или занят системным полем задачи. |
| `invalid_field_ref` | Field reference is invalid | Ссылка на поле не разбирается: ожидается `key` или `QUEUE.key`. |
| `invalid_issue_deadline` | Issue deadline is invalid | Дедлайн пришёл без таймзоны: домысливать её за клиента нельзя. |
| `invalid_issue_description` | Issue description is invalid | Описание задачи длиннее допустимого. |
| `invalid_issue_key` | Issue key is invalid | Ключ задачи не разбирается: ожидается `КЛЮЧ-НОМЕР`, например `TRK-123`. |
| `invalid_issue_summary` | Issue summary is invalid | Название задачи пустое, многострочное или слишком длинное. |
| `invalid_issue_tags` | Issue tags are invalid | Тег задачи многострочный, слишком длинный, либо тегов слишком много. |
| `invalid_page_size` | Page size is out of range | Запрошен размер страницы вне допустимых границ. |
| `invalid_portfolio` | Portfolio definition is invalid | То же самое для портфеля. |
| `invalid_portfolio_key` | Portfolio key is invalid | Ключ портфеля не подходит под шаблон. |
| `invalid_project` | Project definition is invalid | Поле проекта нарушает правило: пустое имя, вывернутый период, лишние участники. |
| `invalid_project_key` | Project key is invalid | Ключ проекта не подходит под шаблон: шаблон уходит в `details.pattern`. |
| `invalid_queue_key` | Queue key is invalid | Ключ очереди не соответствует шаблону. |
| `invalid_saved_filter` | Saved filter definition is invalid | Описание фильтра противоречит само себе: пустое имя либо не ровно один источник. |
| `invalid_search_query` | Search query cannot be parsed | Строка запроса не разбирается. |
| `invalid_stream_cursor` | Stream cursor is unknown or malformed | `Last-Event-ID` не разбирается или указывает на неизвестное событие. |
| `invalid_subscription` | Notification subscription is invalid | Описание подписки нарушает правило. |
| `invalid_tree_depth` | Tree depth is out of range | Запрошена глубина дерева вне допустимых границ. |
| `invalid_wait_timeout` | Wait timeout is out of range | Запрошенное время ожидания вне допустимых границ. |
| `invalid_webhook_subscription` | Webhook subscription is invalid | Описание подписки нарушает правило. |
| `invalid_workflow_graph` | Workflow graph is invalid | Граф не образует цельный процесс от начального статуса до завершения. |
| `issue_resolution_not_allowed` | Resolution is only allowed for a done status | У незавершённой задачи резолюции быть не должно. |
| `issue_resolution_required` | Resolution is required for a done status | Задача в статусе категории `done` обязана иметь резолюцию. |
| `link_self_reference` | Issue cannot be linked to itself | Задачу нельзя связать с самой собой. |
| `search_field_unknown` | Search field is unknown | Имя из запроса не разрешается в поле. |
| `search_operator_not_supported` | Search operator is not supported for this field | Оператор неприменим к этому полю: список допустимых — в `details.allowed`. |
| `search_value_invalid` | Search value is invalid | Значение условия не подходит полю. |
| `transition_requirements_not_met` | Workflow transition requirements are not met | Переход существует, но обязательные поля в целевом состоянии не заполнены. |
| `validation_error` | Validation failed | Входные данные синтаксически корректны, но нарушают правило предметной области. |

## 429 — слишком часто

| Код | Сообщение | Когда возникает |
|---|---|---|
| `stream_connection_limit` | Too many open event streams | Свободных SSE-соединений в этом процессе больше нет. |
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
