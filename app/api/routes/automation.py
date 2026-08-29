"""Автоматика: список правил, их настройка, журнал срабатываний и запуск макроса.

Правило адресуется своим ключом, а не идентификатором строки. Ключ объявлен в коде и
неизменен, а идентификатор строки — служебное значение, которое у одной и той же
установки после переналивки базы будет другим: ссылка на правило в документации или в
скрипте развалилась бы.

Заведения и удаления правил здесь нет намеренно. Правило — это код в репозитории, а
строка состояния появляется сама при синхронизации реестра на старте процесса. Эндпоинт
создания означал бы правило без объявления — то есть строку, которую нечем выполнить.
"""

from typing import Annotated

from fastapi import APIRouter, Path, Query, status

from app.api.deps import CurrentActorDep, CursorQuery, LimitQuery, SessionDep
from app.api.schemas.automation import (
    AutomationRuleRead,
    AutomationRuleUpdate,
    AutomationRunRead,
    MacroRunRequest,
)
from app.api.schemas.common import CollectionResponse, DataResponse
from app.core.sentinels import UNSET
from app.db.pagination import DEFAULT_PAGE_SIZE
from app.domain.automation import RunStatus
from app.services import automation as service
from app.services import issues as issues_service
from app.services import queues as queues_service
from app.services import saved_filters as saved_filters_service

router = APIRouter(prefix="/automation", tags=["automation"])

RuleKeyPath = Annotated[
    str,
    Path(
        description="Rule key declared in the code",
        examples=["close_children_with_parent"],
    ),
]
QueueQuery = Annotated[
    str | None,
    Query(description="Queue key: rules limited to this queue only"),
]
EnabledQuery = Annotated[bool | None, Query(description="Filter by whether the rule is on")]
RuleFilterQuery = Annotated[str | None, Query(description="Rule key to filter the journal by")]
IssueFilterQuery = Annotated[str | None, Query(description="Issue key to filter the journal by")]
# Параметр называется `status` в запросе и `run_status` в сигнатуре: `status` уже занято
# импортом `fastapi.status`, которым задан код ответа макроса. Псевдоним держит имя в
# контракте прежним — переименование параметра сломало бы сгенерированный клиент.
StatusFilterQuery = Annotated[
    RunStatus | None,
    Query(alias="status", description="Filter runs by result"),
]


@router.get("/rules", summary="List automation rules")
async def list_automation_rules(
    session: SessionDep,
    current_actor: CurrentActorDep,
    queue: QueueQuery = None,
    is_enabled: EnabledQuery = None,
    limit: LimitQuery = DEFAULT_PAGE_SIZE,
    cursor: CursorQuery = None,
) -> CollectionResponse[AutomationRuleRead]:
    """Правила вместе с их объявлением: форма, события, расписание и схема параметров.

    Правило, у которого пропало объявление в коде, остаётся в списке с
    `is_available: false`. Прятать его нельзя: оно может значиться включённым, и тогда
    вопрос «почему оно не срабатывает» иначе остался бы без ответа.
    """
    page = await service.list_rules(
        session,
        initiator=current_actor,
        queue=None if queue is None else await queues_service.get_queue_by_key(session, queue),
        is_enabled=is_enabled,
        limit=limit,
        cursor=cursor,
    )
    return CollectionResponse[AutomationRuleRead].of(
        [AutomationRuleRead.of(view) for view in page.items],
        next_cursor=page.next_cursor,
    )


@router.get("/rules/{rule_key}", summary="Read an automation rule")
async def read_automation_rule(
    rule_key: RuleKeyPath,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[AutomationRuleRead]:
    """Правило: что оно делает, включено ли, к чему привязано и как настроено.

    Вместе со значениями параметров приезжает их схема (`params_schema`) — по ней
    интерфейс строит форму настройки, а не догадывается о ней. Правило объявлено кодом,
    поэтому через API меняется только его состояние, но не поведение.
    """
    view = await service.read_rule(session, rule_key, initiator=current_actor)
    return DataResponse[AutomationRuleRead](data=AutomationRuleRead.of(view))


@router.patch("/rules/{rule_key}", summary="Update an automation rule")
async def update_automation_rule(
    rule_key: RuleKeyPath,
    payload: AutomationRuleUpdate,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[AutomationRuleRead]:
    """Включает, выключает и настраивает правило — без перезапуска процессов.

    Параметры заменяются целиком и проверяются схемой самого правила: включённое
    правило с мусорными параметрами падало бы в фоне, и заметили бы это по несделанной
    работе, а не по ошибке.
    """
    rule = await service.get_rule(session, rule_key)
    given = payload.model_dump(exclude_unset=True)

    queue = UNSET
    if "queue" in given:
        queue = (
            None
            if payload.queue is None
            else await queues_service.get_queue_by_key(session, payload.queue)
        )
    saved_filter = UNSET
    if "saved_filter" in given:
        saved_filter = (
            None
            if payload.saved_filter is None
            else await saved_filters_service.get_saved_filter(session, payload.saved_filter)
        )

    view = await service.update_rule(
        session,
        rule,
        initiator=current_actor,
        is_enabled=given.get("is_enabled", UNSET),
        queue=queue,
        params=given.get("params", UNSET),
        saved_filter=saved_filter,
    )
    return DataResponse[AutomationRuleRead](data=AutomationRuleRead.of(view))


@router.post(
    "/rules/{rule_key}/run",
    status_code=status.HTTP_200_OK,
    summary="Run a macro rule for an issue",
)
async def run_automation_macro(
    rule_key: RuleKeyPath,
    payload: MacroRunRequest,
    session: SessionDep,
    current_actor: CurrentActorDep,
) -> DataResponse[AutomationRunRead]:
    """Запускает макрос и отдаёт запись журнала.

    Ответ `200`, а не `201`: ресурс запроса — это выполненное действие, а запись журнала
    — его след, за которым потом никто не ходит по адресу. Ошибка **внутри** правила
    приходит в этом же ответе как `status: failed` с текстом причины, а не пятисоткой:
    проброс исключения откатил бы транзакцию вместе с записью журнала, и единственный
    след неудачного макроса пропал бы ровно тогда, когда он нужен.

    Отказы **до** выполнения — другое дело и приходят ошибкой: правило выключено
    (`automation_rule_disabled`), это не макрос (`automation_rule_kind_mismatch`),
    задача из чужой очереди (`automation_rule_out_of_scope`).
    """
    issue = await issues_service.get_issue_by_key(session, payload.issue)
    outcome = await service.run_macro(
        session,
        rule_key,
        issue=issue,
        initiator=current_actor,
        params=payload.params,
    )
    return DataResponse[AutomationRunRead](data=AutomationRunRead.of(outcome.run))


@router.get("/runs", summary="List automation runs")
async def list_automation_runs(
    session: SessionDep,
    current_actor: CurrentActorDep,
    rule: RuleFilterQuery = None,
    issue: IssueFilterQuery = None,
    run_status: StatusFilterQuery = None,
    limit: LimitQuery = DEFAULT_PAGE_SIZE,
    cursor: CursorQuery = None,
) -> CollectionResponse[AutomationRunRead]:
    """Журнал срабатываний: правило, задача, результат, ошибка, время.

    Пропуски видны наравне с успехами и с ошибками — по ним и отвечают на вопрос
    «почему правило не сработало»: `reason` называет сработавшую защиту
    (`rate_limited`, `chain_depth_exceeded`, `self_triggered`) или решение самого
    правила (`condition_not_met`, `nothing_to_do`).
    """
    page = await service.list_runs(
        session,
        initiator=current_actor,
        rule=None if rule is None else await service.get_rule(session, rule),
        issue=None if issue is None else await issues_service.get_issue_by_key(session, issue),
        status=run_status,
        limit=limit,
        cursor=cursor,
    )
    return CollectionResponse[AutomationRunRead].of(
        [AutomationRunRead.of(run) for run in page.items],
        next_cursor=page.next_cursor,
    )
