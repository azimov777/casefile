"""Доменные ошибки — все в одном месте.

Соглашения требуют, чтобы доменные коды перечислялись в одном файле, а не заводились
по месту возникновения: когда фронтенду понадобится список кодов, его можно прочитать
целиком, а не собирать по репозиторию. Каждая следующая задача дописывает сюда свои.

Базовые семейства (`not_found`, `conflict`, `validation_error`, ...) живут в
`app/core/errors.py`; здесь только их наследники со своим стабильным кодом.

Исключение из правила одно и оно осознанное: ошибка, описывающая не предметную
область, а механизм (недоступна база, испорчен курсор), живёт рядом с этим механизмом.
"""

from app.core.errors import ConflictError, NotFoundError, ValidationError

# --- Акторы ---------------------------------------------------------------------


class ActorNotFoundError(NotFoundError):
    """Актора с таким ключом или идентификатором нет."""

    code = "actor_not_found"
    message = "Actor not found"


class ActorKeyTakenError(ConflictError):
    """Ключ актора уже занят: ключ уникален на всю установку."""

    code = "actor_key_taken"
    message = "Actor key is already taken"


class InvalidActorKeyError(ValidationError):
    """Ключ не соответствует шаблону или зарезервирован."""

    code = "invalid_actor_key"
    message = "Actor key is invalid"


class ActorInactiveError(ConflictError):
    """Актор отключён: выпускать ему токены и действовать от его имени нельзя."""

    code = "actor_inactive"
    message = "Actor is inactive"


class SystemActorProtectedError(ConflictError):
    """Системный актор управляется приложением, а не API.

    Его нельзя ни создать, ни отключить, ни выпустить ему токен: автоматика ходит от
    его имени внутри процесса, и внешний токен на него означал бы возможность выдать
    себя за автоматику.
    """

    code = "system_actor_protected"
    message = "System actor is managed by the application"


# --- Токены доступа -------------------------------------------------------------


class ApiTokenNotFoundError(NotFoundError):
    """Токена с таким идентификатором у актора нет."""

    code = "api_token_not_found"
    message = "API token not found"


# --- Очереди --------------------------------------------------------------------


class QueueNotFoundError(NotFoundError):
    """Очереди с таким ключом нет."""

    code = "queue_not_found"
    message = "Queue not found"


class QueueKeyTakenError(ConflictError):
    """Ключ очереди уже занят: он уникален на всю установку и неизменяем после создания."""

    code = "queue_key_taken"
    message = "Queue key is already taken"


class InvalidQueueKeyError(ValidationError):
    """Ключ очереди не соответствует шаблону."""

    code = "invalid_queue_key"
    message = "Queue key is invalid"


class InvalidIssueKeyError(ValidationError):
    """Ключ задачи не разбирается: ожидается `КЛЮЧ-НОМЕР`, например `TRK-123`."""

    code = "invalid_issue_key"
    message = "Issue key is invalid"


class QueueArchivedError(ConflictError):
    """Очередь в архиве: новые задачи в неё не заводятся.

    Настройки архивной очереди править можно — иначе её нельзя было бы привести в
    порядок перед возвратом из архива.
    """

    code = "queue_archived"
    message = "Queue is archived"


class QueueNotEmptyError(ConflictError):
    """В очереди есть задачи: удалять её нельзя, для этого есть архивация."""

    code = "queue_not_empty"
    message = "Queue still has issues"


# --- Задачи ---------------------------------------------------------------------


class IssueNotFoundError(NotFoundError):
    """Задачи с таким ключом нет."""

    code = "issue_not_found"
    message = "Issue not found"


class IssueVersionConflictError(ConflictError):
    """Версия задачи разошлась: её изменили между чтением и записью.

    Отдельный код, а не общий `conflict`: клиент по нему понимает, что нужно перечитать
    задачу и повторить изменение, а не что запрос был неверным. Тихая перезапись здесь
    хуже отказа — потерянное чужое изменение обнаруживается спустя дни.
    """

    code = "version_conflict"
    message = "Issue was changed by someone else"


class IssueReferencedError(ConflictError):
    """На задачу ссылаются кастомные поля других задач: удалять её нельзя.

    Тихое удаление оставило бы в чужих значениях ключ, за которым ничего нет: форма
    показала бы пустое поле, фильтр по нему не нашёл бы ничего, а понять причину было бы
    нельзя. Сначала снимают ссылки, потом удаляют задачу.
    """

    code = "issue_referenced"
    message = "Issue is referenced by other issues"


class InvalidIssueSummaryError(ValidationError):
    """Название задачи пустое, многострочное или слишком длинное."""

    code = "invalid_issue_summary"
    message = "Issue summary is invalid"


class InvalidIssueDescriptionError(ValidationError):
    """Описание задачи длиннее допустимого."""

    code = "invalid_issue_description"
    message = "Issue description is invalid"


class InvalidIssueDeadlineError(ValidationError):
    """Дедлайн пришёл без таймзоны: домысливать её за клиента нельзя."""

    code = "invalid_issue_deadline"
    message = "Issue deadline is invalid"


class InvalidIssueTagsError(ValidationError):
    """Тег задачи многострочный, слишком длинный, либо тегов слишком много."""

    code = "invalid_issue_tags"
    message = "Issue tags are invalid"


# --- Справочники: статусы, типы задач, резолюции ---------------------------------


class InvalidCatalogKeyError(ValidationError):
    """Ключ записи справочника не соответствует шаблону."""

    code = "invalid_catalog_key"
    message = "Catalog key is invalid"


class InvalidCatalogRefError(ValidationError):
    """Ссылка на запись справочника не разбирается: ожидается `key` или `QUEUE.key`."""

    code = "invalid_catalog_ref"
    message = "Catalog reference is invalid"


class CatalogEntryUnavailableError(ValidationError):
    """Запись существует, но в этой очереди недоступна.

    Две причины: запись принадлежит другой очереди (локальная область) либо отключена.
    В обоих случаях назначать её значением по умолчанию или целью переноса нельзя —
    иначе очередь получила бы конфигурацию, которой не может пользоваться.
    """

    code = "catalog_entry_unavailable"
    message = "Catalog entry is not available in this queue"


class StatusNotFoundError(NotFoundError):
    """Статуса с такой ссылкой нет."""

    code = "status_not_found"
    message = "Status not found"


class IssueTypeNotFoundError(NotFoundError):
    """Типа задачи с такой ссылкой нет."""

    code = "issue_type_not_found"
    message = "Issue type not found"


class ResolutionNotFoundError(NotFoundError):
    """Резолюции с такой ссылкой нет."""

    code = "resolution_not_found"
    message = "Resolution not found"


class StatusKeyTakenError(ConflictError):
    """Ключ статуса занят в этой области: глобально либо внутри очереди."""

    code = "status_key_taken"
    message = "Status key is already taken in this scope"


class IssueTypeKeyTakenError(ConflictError):
    """Ключ типа задачи занят в этой области."""

    code = "issue_type_key_taken"
    message = "Issue type key is already taken in this scope"


class ResolutionKeyTakenError(ConflictError):
    """Ключ резолюции занят в этой области."""

    code = "resolution_key_taken"
    message = "Resolution key is already taken in this scope"


class StatusInUseError(ConflictError):
    """Статус используется: в нём стоят задачи или он назначен очереди по умолчанию.

    Удаление такого статуса запрещено намеренно. Тихое удаление оставило бы задачи со
    ссылкой в никуда и сломало доски и расчёт прогресса проектов, а удаление «с
    переносом» одним движением слишком легко сделать не глядя. Перенос задач в другой
    статус — отдельный явный сценарий; затем статус убирают из живых графов и только
    после этого удаляют из справочника.
    """

    code = "status_in_use"
    message = "Status is in use"


class IssueTypeInUseError(ConflictError):
    """Тип задачи используется: есть задачи этого типа или он назначен по умолчанию."""

    code = "issue_type_in_use"
    message = "Issue type is in use"


class ResolutionInUseError(ConflictError):
    """Резолюция используется задачами."""

    code = "resolution_in_use"
    message = "Resolution is in use"


class StatusCategoryLockedError(ConflictError):
    """Категорию статуса с задачами менять нельзя.

    Категория — это машинный смысл статуса (`new` / `in_progress` / `done`). Смена её
    на лету переопределяет задним числом, какие задачи считаются закрытыми: прогресс
    проектов, доски и отчёты изменятся, хотя ни одна задача не двигалась.
    """

    code = "status_category_locked"
    message = "Status category cannot be changed while issues use the status"


# --- Реестр полей ---------------------------------------------------------------


class InvalidFieldKeyError(ValidationError):
    """Ключ поля не соответствует шаблону или занят системным полем задачи."""

    code = "invalid_field_key"
    message = "Field key is invalid"


class InvalidFieldRefError(ValidationError):
    """Ссылка на поле не разбирается: ожидается `key` или `QUEUE.key`."""

    code = "invalid_field_ref"
    message = "Field reference is invalid"


class FieldNotFoundError(NotFoundError):
    """Поля с такой ссылкой нет."""

    code = "field_not_found"
    message = "Field not found"


class FieldKeyTakenError(ConflictError):
    """Ключ поля занят в этой области: глобально либо внутри очереди."""

    code = "field_key_taken"
    message = "Field key is already taken in this scope"


class InvalidFieldDefinitionError(ValidationError):
    """Описание поля противоречит само себе.

    Перечисление без вариантов, варианты у не-перечисления, дубли ключей вариантов,
    значение по умолчанию не того типа. Причина — в `details.reason`: код один, потому
    что для клиента это одна ситуация «поле описано неверно, вот что именно».
    """

    code = "invalid_field_definition"
    message = "Field definition is invalid"


class FieldTypeLockedError(ConflictError):
    """У поля есть значения: тип и множественность менять нельзя.

    Смена типа задним числом переопределила бы уже записанное: строка «2026-08-27»
    осталась бы в JSONB, но читалась бы как число, а история изменений — как ссылка на
    актора. Переименование и обязательность менять можно сколько угодно.
    """

    code = "field_type_locked"
    message = "Field type cannot be changed while the field has values"


class FieldInUseError(ConflictError):
    """Поле используется задачами: жёстко удалить его нельзя, только скрыть.

    Скрытое поле остаётся в реестре: значения в задачах никуда не деваются и история
    изменений остаётся читаемой, но новые значения в него не пишутся и в конфигурации
    очереди его больше нет.
    """

    code = "field_in_use"
    message = "Field is in use"


class FieldUnavailableError(ValidationError):
    """Поле существует, но в этой очереди или у этого типа задачи неприменимо."""

    code = "field_unavailable"
    message = "Field is not available here"


class FieldValuesInvalidError(ValidationError):
    """Значения кастомных полей не прошли проверку.

    В `details.fields` лежит **весь** список замечаний, а не первое: фронту нужно
    подсветить всю форму за один ответ, а агенту — исправить запрос за одну попытку.
    Форма записи описана в `app/domain/fields.py` (`FieldIssue`).
    """

    code = "field_values_invalid"
    message = "Custom field values failed validation"


# --- Воркфлоу --------------------------------------------------------------------


class WorkflowNotFoundError(NotFoundError):
    """Воркфлоу с таким идентификатором нет."""

    code = "workflow_not_found"
    message = "Workflow not found"


class WorkflowNameTakenError(ConflictError):
    """Имя воркфлоу уникально внутри очереди."""

    code = "workflow_name_taken"
    message = "Workflow name is already taken in this queue"


class TransitionNotFoundError(NotFoundError):
    """Перехода с таким идентификатором нет в указанном воркфлоу."""

    code = "transition_not_found"
    message = "Workflow transition not found"


class InvalidWorkflowGraphError(ValidationError):
    """Граф не образует цельный процесс от начального статуса до завершения."""

    code = "invalid_workflow_graph"
    message = "Workflow graph is invalid"


class WorkflowAssignmentError(ConflictError):
    """Воркфлоу нельзя назначить типу, не оставив существующие задачи вне графа."""

    code = "workflow_assignment_conflict"
    message = "Workflow cannot be assigned to this issue type"


class WorkflowInUseError(ConflictError):
    """Назначенный типам задач воркфлоу нельзя удалить."""

    code = "workflow_in_use"
    message = "Workflow is assigned to issue types"


class WorkflowStatusInUseError(ConflictError):
    """Из графа нельзя убрать статус, в котором стоят задачи этого процесса."""

    code = "workflow_status_in_use"
    message = "Workflow status is used by issues"


class TransitionNotAllowedError(ConflictError):
    """Текущий воркфлоу не разрешает запрошенную смену статуса."""

    code = "transition_not_allowed"
    message = "Workflow transition is not allowed"


class TransitionRequirementsError(ValidationError):
    """Переход существует, но обязательные поля в целевом состоянии не заполнены."""

    code = "transition_requirements_not_met"
    message = "Workflow transition requirements are not met"


class IssueResolutionRequiredError(ValidationError):
    """Задача в статусе категории `done` обязана иметь резолюцию."""

    code = "issue_resolution_required"
    message = "Resolution is required for a done status"


class IssueResolutionNotAllowedError(ValidationError):
    """У незавершённой задачи резолюции быть не должно."""

    code = "issue_resolution_not_allowed"
    message = "Resolution is only allowed for a done status"


# --- Связи между задачами --------------------------------------------------------


class IssueLinkNotFoundError(NotFoundError):
    """Связи с таким идентификатором у этой задачи нет.

    Один код и на несуществующую связь, и на существующую, но принадлежащую другой
    паре задач: связь адресуется в пути своей задачей, и «есть, но не твоя» для
    клиента то же самое, что «нет».
    """

    code = "link_not_found"
    message = "Issue link not found"


class IssueLinkExistsError(ConflictError):
    """Такая связь между этими задачами уже есть.

    Проверяется после приведения к каноническому виду, поэтому «A blocks B» упирается
    в уже существующую «B depends_on A»: это одна связь, записанная с разных сторон.
    """

    code = "link_already_exists"
    message = "Issue link already exists"


class SelfLinkError(ValidationError):
    """Задачу нельзя связать с самой собой."""

    code = "link_self_reference"
    message = "Issue cannot be linked to itself"


class LinkCycleError(ConflictError):
    """Связь замкнула бы иерархию в кольцо.

    Проверка идёт на произвольной глубине, а не только на прямом «А родитель Б, Б
    родитель А»: кольцо из трёх и более задач так же ломает дерево — обход по нему не
    заканчивается, а «родитель» перестаёт означать «выше».
    """

    code = "link_cycle_detected"
    message = "Issue link would create a hierarchy cycle"


class IssueParentExistsError(ConflictError):
    """У задачи уже есть родитель: второго не бывает.

    Иерархия обязана оставаться деревом. С двумя родителями одна и та же задача попала
    бы в выдачу дерева дважды, а «в каком эпике задача» перестало бы иметь единственный
    ответ. Прежнюю связь сначала удаляют, потом заводят новую.
    """

    code = "link_parent_exists"
    message = "Issue already has a parent"


class EpicParentError(ConflictError):
    """У задачи типа «эпик» родителя быть не может.

    Эпик — верхний уровень планирования; вложенный в задачу эпик означал бы, что
    верхний уровень находится внутри нижнего. Ошибка возникает и при создании связи, и
    при попытке сменить тип задачи, у которой родитель уже есть.
    """

    code = "epic_cannot_have_parent"
    message = "An epic cannot have a parent issue"


class InvalidTreeDepthError(ValidationError):
    """Запрошена глубина дерева вне допустимых границ."""

    code = "invalid_tree_depth"
    message = "Tree depth is out of range"


# --- Комментарии -----------------------------------------------------------------


class CommentNotFoundError(NotFoundError):
    """Комментария с таким идентификатором у этой задачи нет.

    Один код и на несуществующий комментарий, и на существующий, но принадлежащий
    другой задаче: комментарий адресуется в пути своей задачей, и «есть, но не в этой
    задаче» для клиента то же самое, что «нет».
    """

    code = "comment_not_found"
    message = "Comment not found"


class CommentDeletedError(ConflictError):
    """Комментарий удалён: править и удалять его повторно нечего.

    Удаление мягкое, поэтому строка на месте и читается — но текста у неё уже нет, и
    правка вернула бы удалённое высказывание в ленту задним числом.
    """

    code = "comment_deleted"
    message = "Comment is deleted"


class InvalidCommentBodyError(ValidationError):
    """Текст комментария пуст или длиннее допустимого."""

    code = "invalid_comment_body"
    message = "Comment body is invalid"


# --- Чеклист ---------------------------------------------------------------------


class ChecklistItemNotFoundError(NotFoundError):
    """Пункта чеклиста с таким идентификатором у этой задачи нет.

    Как и у комментария, чужой пункт неотличим от несуществующего: пункт адресуется в
    пути своей задачей, и по идентификатору из чужой задачи его не переставить.
    """

    code = "checklist_item_not_found"
    message = "Checklist item not found"


class InvalidChecklistItemError(ValidationError):
    """Пункт чеклиста нарушает правило: пустой текст, перенос строки, потолок пунктов.

    Причина всегда в `details.reason`: `required`, `multiline_not_allowed`,
    `too_long`, `too_many_items`, `timezone_required`. Один код на все случаи — по
    той же схеме, что у значений кастомных полей: клиент читает причину, а не
    заводит обработчик под каждый вид нарушения.
    """

    code = "invalid_checklist_item"
    message = "Checklist item is invalid"


# --- Поиск ------------------------------------------------------------------------


class InvalidSearchQueryError(ValidationError):
    """Строка запроса не разбирается.

    В `details` обязательно лежат `position` (индекс символа в строке, с нуля) и
    `reason`. Без позиции агент, получивший «invalid query», уходит в слепой перебор:
    он не видит, какое место строки сервер счёл ошибкой.
    """

    code = "invalid_search_query"
    message = "Search query cannot be parsed"


class SearchFieldUnknownError(ValidationError):
    """Имя из запроса не разрешается в поле.

    Причина — в `details.reason`: `unknown_field` (такого поля нет), `not_searchable`
    (имя занято системой, но искать по нему пока нечем), `not_sortable`,
    `not_selectable`. Один код на все случаи: для клиента это одна ситуация «имя не
    подходит, вот почему», и заводить обработчик под каждый вид незачем.
    """

    code = "search_field_unknown"
    message = "Search field is unknown"


class SearchOperatorNotSupportedError(ValidationError):
    """Оператор неприменим к этому полю: список допустимых — в `details.allowed`."""

    code = "search_operator_not_supported"
    message = "Search operator is not supported for this field"


class SearchValueInvalidError(ValidationError):
    """Значение условия не подходит полю.

    Сюда же сведены ненайденные очередь, статус и актор, названные в фильтре: для
    клиента это не «объект не найден», а неверное значение фильтра, и `404` на поиске
    сбивал бы с толку. Исходный код лежит в `details.reason`.
    """

    code = "search_value_invalid"
    message = "Search value is invalid"


# --- Сохранённые фильтры -----------------------------------------------------------


class SavedFilterNotFoundError(NotFoundError):
    """Сохранённого фильтра с таким идентификатором нет."""

    code = "saved_filter_not_found"
    message = "Saved filter not found"


class SavedFilterNameTakenError(ConflictError):
    """Имя фильтра уникально у владельца: два одноимённых фильтра неразличимы в списке."""

    code = "saved_filter_name_taken"
    message = "Saved filter name is already taken by this owner"


class InvalidSavedFilterError(ValidationError):
    """Описание фильтра противоречит само себе: пустое имя либо не ровно один источник.

    Строка запроса и структурный фильтр — два способа сказать одно и то же, и хранить
    их вместе значило бы завести вопрос «какой из них главный», ответа на который нет.
    """

    code = "invalid_saved_filter"
    message = "Saved filter definition is invalid"


# --- Проекты и портфели ------------------------------------------------------------


class ProjectNotFoundError(NotFoundError):
    """Проекта с таким ключом или идентификатором нет."""

    code = "project_not_found"
    message = "Project not found"


class PortfolioNotFoundError(NotFoundError):
    """Портфеля с таким ключом или идентификатором нет."""

    code = "portfolio_not_found"
    message = "Portfolio not found"


class ProjectKeyTakenError(ConflictError):
    """Ключ проекта уникален на установку: по нему адресуют проект и фильтруют задачи."""

    code = "project_key_taken"
    message = "Project key is already taken"


class PortfolioKeyTakenError(ConflictError):
    """Ключ портфеля уникален на установку.

    Пространства имён у проектов и портфелей при этом **разные**: `alpha` может быть и
    проектом, и портфелем. Они адресуются разными путями (`/projects/alpha` против
    `/portfolios/alpha`) и разными фильтрами, поэтому общий запрет только мешал бы.
    """

    code = "portfolio_key_taken"
    message = "Portfolio key is already taken"


class InvalidProjectKeyError(ValidationError):
    """Ключ проекта не подходит под шаблон: шаблон уходит в `details.pattern`."""

    code = "invalid_project_key"
    message = "Project key is invalid"


class InvalidPortfolioKeyError(ValidationError):
    """Ключ портфеля не подходит под шаблон."""

    code = "invalid_portfolio_key"
    message = "Portfolio key is invalid"


class InvalidProjectError(ValidationError):
    """Поле проекта нарушает правило: пустое имя, вывернутый период, лишние участники.

    Один код на все поля, как у сохранённого фильтра: конкретное поле и причина лежат
    в `details`, и заводить отдельный код под каждое поле значило бы растить контракт
    быстрее, чем растёт польза от него.
    """

    code = "invalid_project"
    message = "Project definition is invalid"


class InvalidPortfolioError(ValidationError):
    """То же самое для портфеля."""

    code = "invalid_portfolio"
    message = "Portfolio definition is invalid"


class PortfolioCycleError(ConflictError):
    """Вложение замкнуло бы кольцо портфелей.

    Проверяется на произвольной глубине, а не только на прямом «A внутри B, B внутри
    A»: кольцо из трёх портфелей ломает обход состава ровно так же, как из двух. Та же
    механика, что у иерархии задач (`link_cycle_detected`).
    """

    code = "portfolio_cycle_detected"
    message = "Portfolio nesting would create a cycle"


class ProjectArchivedError(ConflictError):
    """Проект в архиве и новых задач не принимает.

    Ровно та же граница, что у архивной очереди: архив запрещает **приём новой
    работы**, а не правку самого объекта. Переименовать архивный проект или поправить
    его описание можно — это исправление записи, а не продолжение работы в нём.
    """

    code = "project_archived"
    message = "Project is archived"


class PortfolioArchivedError(ConflictError):
    """Портфель в архиве: вкладывать в него проекты и портфели нельзя.

    Та же граница, что у архивного проекта: приём нового состава запрещён, правка
    собственных полей — нет.
    """

    code = "portfolio_archived"
    message = "Portfolio is archived"
