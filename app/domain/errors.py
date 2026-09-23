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
    PermissionDeniedError,
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
    """Задача в `done` или `cancelled`: поля не меняются, и связи, влияющие на переходы, тоже.

    Влияющие виды — `parent`/`child` и `blocks`/`blocked_by`: они задним числом сделали бы
    неверным уже случившееся. `relates` этим кодом не отвечает никогда: он ничего не
    двигает, и именно им закрытую задачу связывают с её продолжением (`CONCEPT.md`, 3.5).
    """

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
    """Шаг назад по цепочке статусов, отмена и уход в `waiting` требуют причины `reason`."""

    code = "transition_reason_required"
    message = "Transition requires a reason"


class ClosingNotATransitionError(ConflictError):
    """`done` достигается только сценарием закрытия, а не переводом статуса.

    Закрытие подшивает вердикты и сводку и переводит задачу одной транзакцией: у него
    свой вызов (`close_task` в MCP, `POST /tasks/{task_key}/close` в REST). Перевод
    статуса в `done` отдельным ходом отклоняется — двумя дверями в `done` были бы два
    поведения, из которых проверялось бы одно.

    Конфликт состояния, а не ошибка формы: сам ход существует, у него другая дверь.
    """

    code = "closing_not_a_transition"
    message = "Closing a task is a separate call, not a status transition"


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
    """`in_progress → done` требует по каждой проверке положительного вердикта,
    подшитого после последнего входа в `in_progress`.

    Этот заход, а не всё дело: вердикты, подшитые раньше последнего входа в
    `in_progress`, остаются в деле, но не засчитываются, потому что относились к другой
    работе или к другой формулировке проверки.

    Незасчитанные проверки перечислены в `details.checks` парами `check_no` и `reason`:
    `no_verdict` — вердикта в этом заходе нет вовсе, `failed` — последний исход
    провальный. Что делать дальше, ошибка не говорит: это решение исполнителя, а не
    трекера.
    """

    code = "checks_not_passed"
    message = "Some checks have no passing verdict recorded since the last entry into in_progress"


class ActorNotAddressableError(ValidationError):
    """Временный агент спрашивает свои вопросы, а адресовать его нельзя.

    Возникает только у выдачи вопросов «мне»: у токена без участника адресата нет, и
    пустой список молча соврал бы, что вопросов не пришло.
    """

    code = "actor_not_addressable"
    message = "A temporary agent cannot be an addressee; pass an explicit addressee"


class AddresseeWithAnyAddresseeError(ValidationError):
    """В выдаче вопросов назван адресат и тут же снято условие адресата.

    Отказ, а не выбор одного из двух: запрос противоречит сам себе, и любое молчаливое
    предпочтение отдало бы клиенту не тот список, о котором он думает.
    """

    code = "addressee_with_any_addressee"
    message = "Questions are filtered either by addressee or by any addressee, not by both"


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
    блокеры закроются. Задача при этом не «ждёт»: разница со статусом `waiting`
    названа в `check_no_open_blockers` (`app/domain/tasks.py`) — здесь блокера
    дожидается назначатель, читающий ленту.
    """

    code = "task_blocked"
    message = "Task has an open blocker"


class TaskHasUnclosedChildrenError(ConflictError):
    """Закрытие задачи при детях не в `done` и не в `cancelled`.

    Закрытие — это и `done`, и `cancelled`: отменённый родитель оставил бы за собой
    работу, чья причина существовать только что исчезла.

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


class JournalTooManyTasksError(ValidationError):
    """Задач в одном фильтре ленты больше потолка: потолок и присланное — в `details`.

    Не усечение списка молча: ждущий, назвавший шестьдесят дел и получивший записи по
    пятидесяти, прочитал бы тишину по остальным как «там ничего не происходит» — то
    есть как ответ. С числом в подробностях он строит свой цикл из нескольких ожиданий.
    """

    code = "journal_too_many_tasks"
    message = "Too many tasks in one journal filter"


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


# --- Учётные записи и вход -----------------------------------------------------------


class AccountNotFoundError(NotFoundError):
    """Учётной записи с таким идентификатором или почтой нет."""

    code = "account_not_found"
    message = "Account not found"


class AccountEmailTakenError(ConflictError):
    """Почта уже занята другой учётной записью: адреса уникальны без учёта регистра."""

    code = "account_email_taken"
    message = "Account email is already taken"


class InvalidEmailError(ValidationError):
    """Почта не похожа на адрес: нет `@`, пустая часть, пробел или слишком длинная."""

    code = "invalid_email"
    message = "Email is invalid"


class WeakPasswordError(ValidationError):
    """Новый пароль не годится: короче минимума или длиннее потолка.

    `details.reason` называет правило (`too_short`, `too_long`), а `details.min_length` и
    `details.max_length` — границы. Самого пароля в ответе нет никогда.
    """

    code = "weak_password"
    message = "Password does not meet the rules"


class ParticipantHasAccountError(ConflictError):
    """У этого участника учётная запись уже есть: у человека она одна."""

    code = "participant_has_account"
    message = "Participant already has an account"


class AccountRequiresHumanError(ValidationError):
    """Учётную запись заводят только человеку: агенты ходят токенами, входить им некуда."""

    code = "account_requires_human"
    message = "Only a human participant can have an account"


class AdminRequiredError(PermissionDeniedError):
    """Управление людьми открыто только администратору (`docs/CONCEPT.md`, 5.4).

    Отдельный код, а не общий `permission_denied`: клиенту это другое решение — не
    перевыпускать токен с другим набором, а спросить администратора. `details.action`
    называет действие, как у единой точки прав.
    """

    code = "admin_required"
    message = "Only an administrator can manage accounts"


class LastAdminError(ConflictError):
    """Действие оставило бы установку без действующего администратора.

    Отключить или лишить флага последнего действующего администратора нельзя: заводить
    людей и сбрасывать им пароли стало бы некому, кроме команды на сервере.
    """

    code = "last_admin"
    message = "The installation must keep at least one active administrator"


class CurrentPasswordMismatchError(ValidationError):
    """Смена своего пароля прислала неверный прежний пароль.

    Не `401`: токен запроса действует, неверно поле тела, и клиент не должен принимать
    это за конец сеанса.
    """

    code = "current_password_mismatch"
    message = "Current password does not match"


class PasswordAttemptsExceededError(TooManyRequestsError):
    """Неудачных попыток входа за окно столько, сколько разрешено: пароль не проверяется.

    Окон три: на адрес клиента, на почту и общий потолок установки, выше обоих
    (`docs/CONCEPT.md`, 5.4). Какое отказало, говорит `details.scope` — `address`,
    `account` или `installation`; там же `limit` этого окна, `window_seconds` и
    `retry_after` (через сколько секунд освободится место). То же число секунд несёт
    заголовок `Retry-After`.
    """

    code = "password_attempts_exceeded"
    message = "Too many password attempts"

    def response_headers(self) -> dict[str, str]:
        return {"Retry-After": str(self.details["retry_after"])}


# --- Перенос установки (TRK-100) ----------------------------------------------------


class ArchiveFormatUnsupportedError(ValidationError):
    """Документ — не архив установки этой раскладки: чужой `format` или `format_version`.

    `details` называет присланные значения и те, что приёмник понимает (`supported`).
    """

    code = "archive_format_unsupported"
    message = "This is not an installation archive this Casefile can read"


class ArchiveInvalidError(ValidationError):
    """Архив противоречит сам себе или схеме своей ревизии.

    `details.reason` называет, что не так: `duplicate_table`, `excluded_table`,
    `bad_columns`, `row_width` — форма документа; `unknown_table`, `missing_table`,
    `column_mismatch` — таблицы и колонки не те, что у схемы на ревизии архива;
    `rejected_row` — Postgres не принял значение (`details.error` — его сообщение).
    Там же `table`, а где уместно — `row`, `expected` и `actual`.
    """

    code = "archive_invalid"
    message = "The installation archive is malformed"


class ArchiveRevisionUnknownError(ConflictError):
    """Ревизии схемы архива приёмник не знает: архив снят более новым Casefile.

    Переноса на более старую версию нет — миграции назад не идут (TRK-91#8). Выход —
    обновить приёмник и повторить приём. `details.schema_revision` — ревизия архива,
    `details.head` — последняя, которую знает приёмник.
    """

    code = "archive_revision_unknown"
    message = "The archive comes from a newer Casefile; update this installation first"


class InstallationNotEmptyError(ConflictError):
    """Приём архива в установку, где уже есть очереди.

    Архив заменяет данные приёмника целиком, а слияния двух трекеров нет: принять его
    может только пустая установка — свежая, где никто ещё не завёл ни одной очереди.
    `details.queues` — сколько их на приёмнике.
    """

    code = "installation_not_empty"
    message = "Only an installation without queues can take an archive"
