"""Доменные ошибки — все в одном месте.

Соглашения требуют, чтобы доменные коды перечислялись в одном файле, а не заводились
по месту возникновения: когда фронтенду понадобится список кодов, его можно прочитать
целиком, а не собирать по репозиторию. Каждая следующая задача дописывает сюда свои.

Базовые семейства (`not_found`, `conflict`, `validation_error`, ...) живут в
`app/core/errors.py`; здесь только их наследники со своим стабильным кодом.

В списке фундамент (участники, токены, метка временного агента, очереди), задача с
переходами (задача 22), дело — записи агента, обязательная сводка, вердикты
(задача 23), связи между задачами (задача 24) — и отбор задач: разбор языка запросов,
имена полей, операторы и значения (задача 25).

Исключение из правила одно и оно осознанное: ошибка, описывающая не предметную
область, а механизм (недоступна база, испорчен курсор), живёт рядом с этим механизмом.
"""

from app.core.errors import (
    ConflictError,
    NotFoundError,
    TooManyRequestsError,
    UnauthorizedError,
    ValidationError,
)

# --- Участники ------------------------------------------------------------------


class ParticipantNotFoundError(NotFoundError):
    """Участника с таким именем или идентификатором нет."""

    code = "participant_not_found"
    message = "Participant not found"


class ParticipantNameTakenError(ConflictError):
    """Имя участника уже занято: имена уникальны без учёта регистра."""

    code = "participant_name_taken"
    message = "Participant name is already taken"


class InvalidParticipantNameError(ValidationError):
    """Имя участника не соответствует шаблону."""

    code = "invalid_participant_name"
    message = "Participant name is invalid"


# --- Автор действия -------------------------------------------------------------


class ActorLabelRequiredError(UnauthorizedError):
    """Общий агентский токен пришёл без метки временного агента.

    Токен без участника не называет автора сам: подписью становится заголовок
    `X-Actor-Label`. Без него запрос нельзя приписать никому, поэтому это отказ в
    аутентификации, а не ошибка формы запроса — самого действия трекер даже не
    рассматривает.
    """

    code = "actor_label_required"
    message = "Shared agent token requires the X-Actor-Label header"


class InvalidActorLabelError(ValidationError):
    """Метка временного агента не соответствует шаблону."""

    code = "invalid_actor_label"
    message = "Actor label is invalid"


# --- Токены доступа -------------------------------------------------------------


class TokenNotFoundError(NotFoundError):
    """Токена с таким идентификатором нет."""

    code = "token_not_found"
    message = "Token not found"


# --- Очереди --------------------------------------------------------------------


class QueueNotFoundError(NotFoundError):
    """Очереди с таким ключом нет."""

    code = "queue_not_found"
    message = "Queue not found"


class QueueKeyTakenError(ConflictError):
    """Ключ очереди уже занят: ключи уникальны без учёта регистра."""

    code = "queue_key_taken"
    message = "Queue key is already taken"


class InvalidQueueKeyError(ValidationError):
    """Ключ очереди не соответствует шаблону."""

    code = "invalid_queue_key"
    message = "Queue key is invalid"


# --- Задачи ---------------------------------------------------------------------------


class TaskNotFoundError(NotFoundError):
    """Задачи с таким ключом нет."""

    code = "task_not_found"
    message = "Task not found"


class InvalidTaskKeyError(ValidationError):
    """Ключ задачи не разбирается как `КЛЮЧ-НОМЕР`."""

    code = "invalid_task_key"
    message = "Task key is invalid"


class TaskFieldsInvalidError(ValidationError):
    """Одно или несколько полей задачи не проходят проверку; все замечания в `details.fields`."""

    code = "task_fields_invalid"
    message = "Task fields are invalid"


class TaskVersionConflictError(ConflictError):
    """Версия задачи разошлась: её изменили между чтением и записью.

    Отдельный код, а не общий `conflict`: клиент по нему понимает, что нужно перечитать
    задачу и повторить изменение, а не что запрос был неверным. Тихая перезапись здесь
    хуже отказа — потерянное чужое изменение обнаруживается спустя дни.
    """

    code = "version_conflict"
    message = "Task version is outdated"


class TaskClosedError(ConflictError):
    """Задача в `done` или `cancelled`: поля и связи закрытой задачи не меняются."""

    code = "task_closed"
    message = "Task is closed"


class TaskFieldLockedError(ConflictError):
    """Поле не редактируется в этом статусе: содержание задачи меняется только в `backlog`.

    Это конфликт состояния, а не ошибка формы запроса: тот же запрос пройдёт, когда
    задача вернётся в `backlog`.
    """

    code = "task_field_locked"
    message = "Field cannot be changed in the current status"


class TransitionNotAllowedError(ConflictError):
    """Перехода между этими статусами нет в таблице; допустимые перечислены в `details.allowed`."""

    code = "transition_not_allowed"
    message = "Transition is not allowed"


class TransitionReasonRequiredError(ValidationError):
    """Шаг назад по цепочке статусов и отмена требуют причины `reason`."""

    code = "transition_reason_required"
    message = "Transition requires a reason"


class TaskSectionsIncompleteError(ValidationError):
    """Перед `open` четыре раздела должны быть заполнены, а `checks` — не пуст.

    Незаполненные разделы перечислены в `details.fields` все сразу.
    """

    code = "task_sections_incomplete"
    message = "Task sections are incomplete"


# --- Дело ---------------------------------------------------------------------------


class EntryNotFoundError(NotFoundError):
    """Записи с таким номером в этой задаче нет."""

    code = "entry_not_found"
    message = "Case entry not found"


class EntryFieldsInvalidError(ValidationError):
    """Запись не проходит проверку формы; все замечания сразу — в `details.fields`.

    Один код на все замечания к записи — по той же причине, что и у полей задачи: агент
    исправляет запрос за одну попытку, читая список, а не за пять кругов «исправил
    одно — вылезло другое». Что именно не так, говорит `reason` каждого замечания:
    `required`, `not_allowed`, `service_type`, `out_of_range`, `unknown_participant`,
    `unknown_entry`, `not_a_question`.
    """

    code = "entry_fields_invalid"
    message = "Case entry fields are invalid"


class SummaryRequiredError(ConflictError):
    """Выход из `in_progress` требует сводки, подшитой после последнего входа в него.

    Конфликт состояния, а не ошибка формы запроса: тот же переход пройдёт, как только
    сводка появится. Это единственная защита от вежливого ухода из работы без справки
    для преемника (`CONCEPT.md`, 5.3).
    """

    code = "summary_required"
    message = "Transition out of in_progress requires a summary"


class ChecksNotPassedError(ConflictError):
    """`review → done` требует по каждой проверке положительного вердикта текущего обзора.

    Текущий обзор — то, что подшито после последнего входа в `review`: вердикты
    прошлых обзоров остаются в деле, но не засчитываются, потому что относились к
    другому выходу или к другой формулировке проверки.

    Проверки без положительного вердикта перечислены в `details.checks`: и те, по
    которым вердикта в этом обзоре нет вовсе, и те, где последний исход — `failed`.
    """

    code = "checks_not_passed"
    message = "Some review checks have no passing verdict"


class ActorNotAddressableError(ValidationError):
    """Временный агент спрашивает свои вопросы, а адресовать его нельзя.

    Возникает только у выдачи вопросов «мне»: у токена без участника адресата нет, и
    пустой список молча соврал бы, что вопросов не пришло.
    """

    code = "actor_not_addressable"
    message = "A temporary agent cannot be an addressee; pass an explicit addressee"


# --- Связи ----------------------------------------------------------------------------


class InvalidLinkKindError(ValidationError):
    """Такого вида связи нет; допустимые перечислены в `details.allowed`."""

    code = "invalid_link_kind"
    message = "Link kind is invalid"


class LinkSelfError(ValidationError):
    """Связь задачи с самой собой запрещена — любого вида, включая `relates`."""

    code = "link_self_not_allowed"
    message = "A task cannot be linked to itself"


class LinkExistsError(ConflictError):
    """Такая связь между этими задачами уже есть.

    Конфликт состояния, а не ошибка формы: запрос правильный, просто его результат уже
    достигнут. Повтор ловится ещё и уникальным ограничением в базе — но только потому,
    что направление приведено к каноническому виду до вставки.
    """

    code = "link_exists"
    message = "Link already exists"


class LinkNotFoundError(NotFoundError):
    """Связи такого вида между этими задачами нет.

    Отдельный код, а не `task_not_found`: обе задачи существуют, нет именно связи, и
    клиенту это разные действия — перечитать карточку, а не проверять ключ.
    """

    code = "link_not_found"
    message = "Link not found"


class LinkCycleError(ConflictError):
    """Связь замкнула бы кольцо в иерархии или в блокировках.

    Проверяется по рёбрам **одного** вида: иерархия и блокировки — два независимых
    графа, и родитель, заблокированный своими детьми, кольцом не является
    (`CONCEPT.md`, 3.5). Обе стороны отказанной связи лежат в `details`.
    """

    code = "link_cycle_detected"
    message = "Link would create a cycle"


class TaskBlockedError(ConflictError):
    """Вход в `in_progress` при незакрытом блокере: ключи блокеров в `details.blockers`.

    Конфликт состояния, а не ошибка формы запроса: тот же переход пройдёт, как только
    блокеры закроются. Задача при этом не «ждёт» — статуса ожидания в трекере нет
    (`CONCEPT.md`, 4.6), ждёт назначатель, читающий ленту.
    """

    code = "task_blocked"
    message = "Task has an open blocker"


class TaskHasUnclosedChildrenError(ConflictError):
    """Переход в `done` при детях не в `done` и не в `cancelled`.

    Незакрытые дети перечислены в `details.children`. Статусы по связям не
    распространяются: трекер не закрывает детей сам, он только не даёт закрыть родителя.
    """

    code = "task_has_unclosed_children"
    message = "Task has children that are not closed"


# --- Поиск ------------------------------------------------------------------------------


class InvalidSearchQueryError(ValidationError):
    """Строка на языке запросов не разбирается.

    В `details` — сама строка, позиция символа с нуля и причина отказа; там же, где
    выбор конечен, `expected` или `allowed`. Позиция обязательна: без неё агент
    исправляет запрос перебором, а не чтением ответа.
    """

    code = "invalid_search_query"
    message = "Search query cannot be parsed"


class SearchFieldUnknownError(ValidationError):
    """Имени поля отбора или ключа сортировки нет: допустимые перечислены в `details.allowed`.

    Не `404`: для поиска незнакомое имя — неверный фильтр, а не отсутствующий ресурс, и
    `404` на списке задач сбивал бы клиента с толку.
    """

    code = "search_field_unknown"
    message = "Search field is unknown"


class SearchOperatorNotSupportedError(ValidationError):
    """Оператор к этому полю неприменим: допустимые перечислены в `details.allowed`.

    Отдельный код от «неверного значения»: клиент чинит эти два случая по-разному —
    здесь он меняет форму условия, а не то, что в нём написано.
    """

    code = "search_operator_not_supported"
    message = "Operator is not supported for this field"


class SearchValueInvalidError(ValidationError):
    """Значение условия не разрешается: нет такой очереди, статуса, не число.

    В `details` — имя поля, позиция значения в исходной строке и причина; у полей с
    конечным набором значений там же `allowed`.
    """

    code = "search_value_invalid"
    message = "Search value is invalid"


# --- Лента журнала ------------------------------------------------------------------


class JournalWaitTooLongError(ValidationError):
    """Запрошенное ожидание больше потолка: потолок и запрошенное лежат в `details`.

    Не срезание до потолка молча: ждущий, попросивший десять минут и получивший минуту,
    решил бы по пустому ответу, что за десять минут ничего не случилось. Отказ с числом
    в подробностях позволяет ему сразу построить свой цикл из нескольких ожиданий.
    """

    code = "journal_wait_too_long"
    message = "Requested wait exceeds the ceiling"


class InvalidJournalCursorError(ValidationError):
    """`Last-Event-ID` потока не разбирается как сквозной номер записи.

    Молчаливый старт «с текущего момента» был бы хуже отказа: клиент считал бы себя
    догнавшим, не будучи им, и разошёлся бы с сервером незаметно. Несуществующий номер
    при этом законен — записи постоянны, и продолжить можно с любого номера.
    """

    code = "invalid_journal_cursor"
    message = "Last-Event-ID is not a journal sequence number"


class JournalStreamLimitError(TooManyRequestsError):
    """Открытых потоков журнала на этом процессе столько, сколько разрешено настройкой.

    В `details` — сколько открыто и сколько можно. Отказ приходит **до** первого кадра:
    после `200` сказать «нельзя» уже нечем, и клиент увидел бы обрыв без объяснения.
    """

    code = "journal_stream_limit"
    message = "Too many open journal streams"


# --- Идемпотентность ------------------------------------------------------------------


class InvalidIdempotencyKeyError(ValidationError):
    """Ключ идемпотентности пуст или длиннее допустимого.

    Отказ, а не молчаливый пропуск ключа: клиент, чей ключ выбросили, считает вызов
    защищённым от повтора, не будучи защищённым, — и узнаёт об этом вторым объектом.
    """

    code = "invalid_idempotency_key"
    message = "Idempotency key is invalid"


class IdempotencyKeyReusedError(ConflictError):
    """Ключ идемпотентности уже использован другим запросом.

    Ключ обещает «это тот же самый вызов», и обещание проверяется отпечатком: тот же
    ключ с другим телом или на другой операции означает, что клиент переиспользовал
    ключ. В `details` — операция, за которой ключ закреплён, и срок его жизни: этого
    хватает, чтобы понять, повторять с новым ключом или чинить генератор ключей.
    """

    code = "idempotency_key_reused"
    message = "Idempotency key was used for a different request"
