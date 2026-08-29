"""Наполнение установки демо-данными.

Фронтенд, который разрабатывают на пустой базе, рисуется по воображаемым данным: пустая
доска, пустой инбокс, пустой прогресс. Половина недоделок такого интерфейса всплывает
только на данных — переполненная колонка, длинное название, задача без исполнителя.
Поэтому демо-набор входит в поставку и разворачивается одной командой.

## Всё создаётся сценариями, а не вставками в базу

Ни одной прямой вставки здесь нет. Задача, положенная в таблицу мимо
`app/services/issues.py`, не имеет ни истории изменений, ни события в outbox — то есть
на таких данных нельзя проверить ни автоматику, ни уведомления, ни поток событий, ради
которых демо-контур во многом и нужен. Цена — набор создаётся дольше; она осознанная.

Отсюда же следствие, которое надо знать: наполнение **порождает события**. В поднятом
контуре их разберёт воркер, сработают правила и придут уведомления. Это не побочный
эффект, а часть замысла: сразу после команды у акторов непустой инбокс.

## Что именно создаётся

Две очереди с разными процессами (обычный и с ревью), общие и локальные поля, эпик с
подзадачами, зависимость между задачами, обсуждение с упоминанием, чеклист, проект
поперёк двух очередей внутри портфеля, сохранённый фильтр, доска с колонками под **все**
статусы процесса и **включённое правило автоматики**.

Правило включается намеренно: все поставочные правила приезжают выключенными, и
демо-контур без единого включённого показывал бы трекер без механики, ради которой он
во многом и строится. Включается `close_children_with_parent` в режиме `announce` —
самый безобидный: он пишет комментарий, а не закрывает чужие задачи.

## Повторный запуск

Команда не идемпотентна и не пытается ею быть: «доложить недостающее» в графе из задач,
связей и рангов — это отдельная механика сложнее самого набора. Вместо этого наличие
демо-данных проверяется заранее (`demo_is_present`), и команда отказывается работать,
называя способ начать заново. Начать заново — значит пересоздать том с базой; для
демо-данных это дешевле любой чистки.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.actor import Actor
from app.db.models.catalog import IssueType, Resolution, Status
from app.db.models.issue import Issue
from app.db.models.queue import Queue
from app.db.repositories.automation import AutomationRuleRepository
from app.db.repositories.queues import QueueRepository
from app.domain.actors import ActorType
from app.domain.catalogs import CatalogKind
from app.domain.fields import FieldOption, FieldValueType
from app.domain.issues import IssuePriority
from app.domain.links import LinkType
from app.domain.projects import ProjectStatus
from app.domain.workflows import WorkflowTemplateKey
from app.services import actors as actors_service
from app.services import automation as automation_service
from app.services import boards as boards_service
from app.services import checklists as checklists_service
from app.services import comments as comments_service
from app.services import fields as fields_service
from app.services import issues as issues_service
from app.services import links as links_service
from app.services import projects as projects_service
from app.services import queues as queues_service
from app.services import saved_filters as saved_filters_service
from app.services import workflow as workflow_service
from app.services.boards import ColumnDraft
from app.services.issues import IssueChanges

#: Ключи очередей демо-набора. По ним же определяется, что набор уже развёрнут.
DEV_QUEUE_KEY = "TRK"
OPS_QUEUE_KEY = "OPS"

#: Правило, которое демо-набор включает. Режим — по умолчанию `announce`.
DEMO_RULE_KEY = "close_children_with_parent"


@dataclass(slots=True)
class DemoReport:
    """Что создано. Печатается командой, чтобы результат был виден без похода в базу."""

    actors: list[str] = field(default_factory=list)
    queues: list[str] = field(default_factory=list)
    fields: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    projects: list[str] = field(default_factory=list)
    boards: list[str] = field(default_factory=list)
    rules: list[str] = field(default_factory=list)

    def lines(self) -> list[str]:
        return [
            f"actors:   {', '.join(self.actors)}",
            f"queues:   {', '.join(self.queues)}",
            f"fields:   {', '.join(self.fields)}",
            f"issues:   {len(self.issues)} ({', '.join(self.issues)})",
            f"projects: {', '.join(self.projects)}",
            f"boards:   {', '.join(self.boards)}",
            f"rules:    {', '.join(self.rules)}",
        ]


async def demo_is_present(session: AsyncSession) -> bool:
    """Демо-набор уже развёрнут: существует хотя бы одна из его очередей."""
    repository = QueueRepository(session)
    for key in (DEV_QUEUE_KEY, OPS_QUEUE_KEY):
        if await repository.get_by_key(key) is not None:
            return True
    return False


async def seed_demo(session: AsyncSession, *, owner: Actor | None = None) -> DemoReport:
    """Разворачивает демо-набор. Возвращает отчёт о созданном.

    `owner` — актор, от чьего имени идёт наполнение; по умолчанию заводится тот же
    владелец, что и командой `init`. Все объекты создаются от живых акторов, а не от
    системного: системный актор — исполнитель автоматики, и набор, созданный им,
    показывал бы историю, которой в жизни не бывает.
    """
    report = DemoReport()
    people = await _actors(session, owner=owner, report=report)
    initiator = people.owner

    dev = await _dev_queue(session, initiator=initiator, report=report)
    ops = await _ops_queue(session, initiator=initiator, report=report)
    await _fields(session, initiator=initiator, ops=ops, report=report)

    issues = await _issues(session, people=people, dev=dev, ops=ops, report=report)
    await _links(session, initiator=initiator, issues=issues)
    await _discussion(session, people=people, issues=issues)
    await _progress(session, people=people, issues=issues)
    await _planning(session, people=people, issues=issues, report=report)
    await _board(session, initiator=initiator, dev=dev, report=report)
    await _automation(session, initiator=initiator, dev=dev, report=report)
    return report


@dataclass(frozen=True, slots=True)
class _People:
    """Акторы демо-набора, названные по ролям, а не по индексам списка."""

    owner: Actor
    alice: Actor
    bob: Actor
    agent: Actor


@dataclass(frozen=True, slots=True)
class _Issues:
    """Задачи демо-набора под именами, по которым их зовут дальнейшие шаги."""

    epic: Issue
    card: Issue
    errors: Issue
    stream_bug: Issue
    demo: Issue
    backup: Issue
    disk: Issue
    image: Issue

    def all(self) -> tuple[Issue, ...]:
        return (
            self.epic,
            self.card,
            self.errors,
            self.stream_bug,
            self.demo,
            self.backup,
            self.disk,
            self.image,
        )


async def _actors(
    session: AsyncSession,
    *,
    owner: Actor | None,
    report: DemoReport,
) -> _People:
    """Двое людей и агент рядом с владельцем.

    Через `ensure_actor`, а не `create_actor`: команду запускают и на установке, где
    `init` уже завёл владельца, и падать на этом было бы нелепо.
    """
    resolved_owner = owner
    if resolved_owner is None:
        resolved_owner, _ = await actors_service.ensure_actor(
            session,
            actor_type=ActorType.HUMAN,
            key="owner",
            display_name="Owner",
        )
    alice, _ = await actors_service.ensure_actor(
        session,
        actor_type=ActorType.HUMAN,
        key="alice",
        display_name="Алиса Петрова",
    )
    bob, _ = await actors_service.ensure_actor(
        session,
        actor_type=ActorType.HUMAN,
        key="bob",
        display_name="Борис Ким",
    )
    agent, _ = await actors_service.ensure_actor(
        session,
        actor_type=ActorType.AGENT,
        key="release_bot",
        display_name="Релизный бот",
    )
    report.actors = [resolved_owner.key, alice.key, bob.key, agent.key]
    return _People(owner=resolved_owner, alice=alice, bob=bob, agent=agent)


async def _dev_queue(session: AsyncSession, *, initiator: Actor, report: DemoReport) -> Queue:
    """Очередь разработки: процесс с ревью, поэтому у неё появляется свой статус.

    Шаблон `review` заводит локальный `TRK.review` — глобального такого статуса нет.
    Это и нужно показать: очередь владеет процессом, и её статус не обязан быть общим.
    """
    queue = await queues_service.create_queue(
        session,
        initiator=initiator,
        key=DEV_QUEUE_KEY,
        name="Разработка трекера",
        description="Очередь команды, которая делает сам трекер",
    )
    workflow = await workflow_service.create_from_template(
        session,
        queue,
        initiator=initiator,
        template_key=WorkflowTemplateKey.REVIEW,
        name="Разработка с ревью",
    )
    for issue_type in await _queue_issue_types(session, queue, initiator=initiator):
        await workflow_service.assign_workflow(session, workflow, issue_type, initiator=initiator)
    report.queues.append(queue.key)
    return queue


async def _ops_queue(session: AsyncSession, *, initiator: Actor, report: DemoReport) -> Queue:
    """Очередь эксплуатации: простой процесс и свой набор типов задач.

    Второй процесс в наборе не для количества: две очереди с разными графами — самый
    короткий способ увидеть, что доска, поиск и автоматика опираются на категорию
    статуса, а не на его название.
    """
    queue = await queues_service.create_queue(
        session,
        initiator=initiator,
        key=OPS_QUEUE_KEY,
        name="Эксплуатация",
        description="Дежурство, инфраструктура и всё, что горит",
        issue_type_refs=["task", "bug"],
        default_issue_type_ref="task",
    )
    workflow = await workflow_service.create_from_template(
        session,
        queue,
        initiator=initiator,
        template_key=WorkflowTemplateKey.SIMPLE,
        name="Дежурный процесс",
    )
    for issue_type in await _queue_issue_types(session, queue, initiator=initiator):
        await workflow_service.assign_workflow(session, workflow, issue_type, initiator=initiator)
    report.queues.append(queue.key)
    return queue


async def _fields(
    session: AsyncSession,
    *,
    initiator: Actor,
    ops: Queue,
    report: DemoReport,
) -> None:
    """Одно глобальное поле и одно локальное — чтобы обе области действия были видны."""
    await fields_service.create_field(
        session,
        initiator=initiator,
        key="component",
        name="Компонент",
        value_type=FieldValueType.ENUM,
        is_multiple=True,
        options=[
            FieldOption(key="api", name="REST API"),
            FieldOption(key="mcp", name="MCP-сервер"),
            FieldOption(key="db", name="База данных"),
            FieldOption(key="docs", name="Документация"),
        ],
        display_order=10,
    )
    await fields_service.create_field(
        session,
        initiator=initiator,
        key="severity",
        name="Критичность",
        value_type=FieldValueType.ENUM,
        queue=ops,
        options=[
            FieldOption(key="minor", name="Незначительная"),
            FieldOption(key="major", name="Серьёзная"),
            FieldOption(key="critical", name="Критическая"),
        ],
        display_order=20,
    )
    report.fields = ["component", f"{ops.key}.severity"]


async def _issues(
    session: AsyncSession,
    *,
    people: _People,
    dev: Queue,
    ops: Queue,
    report: DemoReport,
) -> _Issues:
    """Восемь задач: эпик с подзадачами в разработке и три дежурные в эксплуатации."""
    epic_type = await _issue_type(session, dev, "epic", initiator=people.owner)
    bug_type = await _issue_type(session, dev, "bug", initiator=people.owner)
    ops_bug_type = await _issue_type(session, ops, "bug", initiator=people.owner)
    soon = datetime.now(UTC) + timedelta(days=3)

    epic = await issues_service.create_issue(
        session,
        initiator=people.owner,
        queue=dev,
        issue_type=epic_type,
        summary="Публичный API версии 1",
        description="Собрать контракт целиком и довести его до состояния, пригодного фронтенду",
        assignee=people.owner,
        # Агент подписан на эпик намеренно: правило автоматики пишет комментарий именно
        # сюда, и без наблюдателя уведомлению было бы некуда прийти.
        followers=[people.agent],
        tags=["контракт"],
    )
    card = await issues_service.create_issue(
        session,
        initiator=people.alice,
        queue=dev,
        summary="Карточка задачи одним запросом",
        description="Экран задачи не должен начинаться с пяти обращений подряд",
        assignee=people.alice,
        priority=IssuePriority.MAJOR,
        tags=["контракт", "фронтенд"],
        values={"component": ["api"]},
    )
    errors = await issues_service.create_issue(
        session,
        initiator=people.owner,
        queue=dev,
        summary="Справочник кодов ошибок",
        description="Коды собраны в одном месте и выгружаются командой",
        assignee=people.agent,
        followers=[people.alice],
        values={"component": ["api", "docs"]},
    )
    stream_bug = await issues_service.create_issue(
        session,
        initiator=people.bob,
        queue=dev,
        issue_type=bug_type,
        summary="Ошибки потока событий описаны как text/event-stream",
        description="Класс ответа задаёт тип содержимого всем ответам операции, включая 401",
        assignee=people.bob,
        priority=IssuePriority.BLOCKER,
        values={"component": ["api"]},
    )
    demo = await issues_service.create_issue(
        session,
        initiator=people.owner,
        queue=dev,
        summary="Демо-данные одной командой",
        description="Фронтенд не должен разрабатываться на пустой базе",
        assignee=people.owner,
        values={"component": ["db"]},
    )
    backup = await issues_service.create_issue(
        session,
        initiator=people.bob,
        queue=ops,
        summary="Настроить резервное копирование базы",
        assignee=people.bob,
        deadline=soon,
        values={f"{ops.key}.severity": "major"},
    )
    disk = await issues_service.create_issue(
        session,
        initiator=people.owner,
        queue=ops,
        issue_type=ops_bug_type,
        summary="Диск под данными заполнен на 90%",
        assignee=people.owner,
        priority=IssuePriority.BLOCKER,
        tags=["дежурство"],
        values={f"{ops.key}.severity": "critical"},
    )
    image = await issues_service.create_issue(
        session,
        initiator=people.bob,
        queue=ops,
        summary="Обновить образ PostgreSQL до 17.4",
        values={f"{ops.key}.severity": "minor"},
    )
    issues = _Issues(
        epic=epic,
        card=card,
        errors=errors,
        stream_bug=stream_bug,
        demo=demo,
        backup=backup,
        disk=disk,
        image=image,
    )
    report.issues = [issue.key for issue in issues.all()]
    return issues


async def _links(session: AsyncSession, *, initiator: Actor, issues: _Issues) -> None:
    """Эпик с тремя подзадачами и одна зависимость между ними."""
    for child in (issues.card, issues.errors, issues.demo):
        await links_service.create_link(
            session,
            initiator=initiator,
            source=child,
            link_type=LinkType.SUBTASK_OF,
            target=issues.epic,
        )
    await links_service.create_link(
        session,
        initiator=initiator,
        source=issues.demo,
        link_type=LinkType.DEPENDS_ON,
        target=issues.errors,
    )


async def _discussion(session: AsyncSession, *, people: _People, issues: _Issues) -> None:
    """Обсуждение с упоминанием и чеклист с одним отмеченным пунктом."""
    await comments_service.add_comment(
        session,
        issues.card,
        initiator=people.alice,
        body="@release_bot посмотри, что отдаёт карточка: переходов там быть не должно больше пяти",
    )
    await comments_service.add_comment(
        session,
        issues.card,
        initiator=people.agent,
        body="Проверил: пять переходов, из них два недоступны без резолюции",
    )
    await comments_service.add_comment(
        session,
        issues.stream_bug,
        initiator=people.bob,
        body="Ловится тестом схемы, а не чтением кода: маршрут выглядит правильным",
    )

    first = await checklists_service.add_item(
        session,
        issues.card,
        initiator=people.alice,
        text="Собрать схему ответа",
    )
    await checklists_service.add_item(
        session,
        issues.card,
        initiator=people.alice,
        text="Отдать первую страницу комментариев и курсор",
        assignee=people.alice,
    )
    await checklists_service.add_item(
        session,
        issues.card,
        initiator=people.alice,
        text="Проверить, что переходы считаются от текущего статуса",
    )
    await checklists_service.set_item_done(
        session,
        first,
        issue=issues.card,
        initiator=people.alice,
        is_done=True,
    )


async def _progress(session: AsyncSession, *, people: _People, issues: _Issues) -> None:
    """Проводит часть задач по процессу — ради истории изменений, а не ради статусов.

    Задача, у которой в журнале только «создана», не показывает ни истории, ни ленты
    событий, ни прогресса проекта. Поэтому переходы делаются настоящие: через
    `available_transitions` и `transition_issue`, со всеми проверками процесса.
    """
    await _move(session, issues.card, "Start progress", initiator=people.alice)
    await _move(session, issues.card, "Send to review", initiator=people.alice)

    await _move(session, issues.stream_bug, "Start progress", initiator=people.bob)
    await _move(session, issues.stream_bug, "Send to review", initiator=people.bob)
    await _move(
        session,
        issues.stream_bug,
        "Complete",
        initiator=people.bob,
        resolution=await _resolution(session, "done", initiator=people.bob),
    )

    await _move(session, issues.disk, "Start progress", initiator=people.owner)
    await _move(
        session,
        issues.image,
        "Start progress",
        initiator=people.bob,
    )
    await _move(
        session,
        issues.image,
        "Complete",
        initiator=people.bob,
        resolution=await _resolution(session, "done", initiator=people.bob),
    )


async def _planning(
    session: AsyncSession,
    *,
    people: _People,
    issues: _Issues,
    report: DemoReport,
) -> None:
    """Проект поперёк двух очередей внутри портфеля.

    Задачи берутся из обеих очередей намеренно: проект, собранный из одной, ничем не
    отличался бы от самой очереди, и главное его свойство осталось бы непоказанным.
    """
    portfolio = await projects_service.create_portfolio(
        session,
        initiator=people.owner,
        key="platform",
        name="Платформа",
        description="Всё, что делает команда платформы",
        lead=people.owner,
        status=ProjectStatus.IN_PROGRESS,
    )
    project = await projects_service.create_project(
        session,
        initiator=people.owner,
        key="alpha",
        name="Публичный API v1",
        description="Контракт, по которому фронтенд пишется без вопросов",
        lead=people.alice,
        members=[people.alice, people.bob, people.agent],
        status=ProjectStatus.IN_PROGRESS,
        portfolio=portfolio,
        tags=["контракт"],
    )
    await projects_service.add_issues(
        session,
        project,
        initiator=people.owner,
        issues=[issues.card, issues.errors, issues.demo, issues.stream_bug, issues.backup],
    )
    report.projects = [portfolio.key, project.key]


async def _board(
    session: AsyncSession,
    *,
    initiator: Actor,
    dev: Queue,
    report: DemoReport,
) -> None:
    """Доска поверх сохранённого фильтра, с колонками под **все** статусы процесса.

    Полное покрытие статусов здесь не украшение: задача в статусе, не разложенном ни в
    одну колонку, через колонки доски не видна. Демо-набор, оставляющий такую дыру, учил
    бы неверному.
    """
    saved_filter = await saved_filters_service.create_saved_filter(
        session,
        initiator=initiator,
        name="Разработка трекера",
        description="Всё, что делает команда трекера",
        query=f"queue: {dev.key}",
    )
    columns = [
        ("Бэклог", "open"),
        ("В работе", "in_progress"),
        ("Ревью", f"{dev.key}.review"),
        ("Готово", "closed"),
    ]
    board = await boards_service.create_board(
        session,
        initiator=initiator,
        name="Разработка",
        description="Колонки покрывают все статусы процесса с ревью",
        saved_filter=saved_filter,
        columns=[
            ColumnDraft(
                name=name,
                statuses=[await _status(session, ref, initiator=initiator)],
            )
            for name, ref in columns
        ],
    )
    report.boards = [board.name]


async def _automation(
    session: AsyncSession,
    *,
    initiator: Actor,
    dev: Queue,
    report: DemoReport,
) -> None:
    """Включает правило автоматики и привязывает его к очереди разработки.

    Без включённого правила демо-контур показывает трекер без механики, ради которой он
    во многом и строится: сквозной сценарий «правило сработало → пришло уведомление →
    агент забрал его через MCP» не на чем прогнать.

    Режим остаётся `announce` — тот, что приезжает по умолчанию: правило комментирует
    родителя, а не закрывает чужие задачи. Массовое закрытие включают осознанно, и
    демо-набор такого решения за пользователя не принимает.
    """
    # Синхронизация здесь, а не надежда на старт API: команду запускают отдельным
    # контейнером, и строки состояния под правила в свежей базе может ещё не быть.
    await automation_service.sync_rules(session)
    rules = {rule.rule_key: rule for rule in await AutomationRuleRepository(session).list_all()}
    rule = rules[DEMO_RULE_KEY]
    await automation_service.update_rule(
        session,
        rule,
        initiator=initiator,
        is_enabled=True,
        queue=dev,
    )
    report.rules = [DEMO_RULE_KEY]


async def _queue_issue_types(
    session: AsyncSession,
    queue: Queue,
    *,
    initiator: Actor,
) -> list[IssueType]:
    """Типы задач, подключённые к очереди."""
    config = await queues_service.get_queue_config(session, queue, initiator=initiator)
    return list(config.issue_types)


async def _issue_type(
    session: AsyncSession,
    queue: Queue,
    ref: str,
    *,
    initiator: Actor,
) -> IssueType:
    entry = await queues_service.resolve_catalog_ref(
        session, CatalogKind.ISSUE_TYPE, ref, initiator=initiator
    )
    assert isinstance(entry, IssueType)
    return entry


async def _status(session: AsyncSession, ref: str, *, initiator: Actor) -> Status:
    entry = await queues_service.resolve_catalog_ref(
        session, CatalogKind.STATUS, ref, initiator=initiator
    )
    assert isinstance(entry, Status)
    return entry


async def _resolution(session: AsyncSession, ref: str, *, initiator: Actor) -> Resolution:
    entry = await queues_service.resolve_catalog_ref(
        session, CatalogKind.RESOLUTION, ref, initiator=initiator
    )
    assert isinstance(entry, Resolution)
    return entry


async def _move(
    session: AsyncSession,
    issue: Issue,
    transition_name: str,
    *,
    initiator: Actor,
    resolution: Resolution | None = None,
) -> None:
    """Проводит задачу по названному ребру процесса.

    По имени перехода, а не по идентификатору: идентификаторы у каждой установки свои,
    а имена задаёт шаблон процесса. Отсутствие ребра — ошибка набора, а не повод
    промолчать: молча пропущенный переход дал бы демо-данные, у которых половина задач
    необъяснимо стоит в первом статусе.
    """
    transition_id = await _transition_id(session, issue, transition_name, initiator=initiator)
    changes = IssueChanges() if resolution is None else IssueChanges(resolution=resolution)
    await issues_service.transition_issue(
        session,
        issue,
        transition_id,
        initiator=initiator,
        changes=changes,
    )


async def _transition_id(
    session: AsyncSession,
    issue: Issue,
    transition_name: str,
    *,
    initiator: Actor,
) -> uuid.UUID:
    available = await workflow_service.available_transitions(
        session,
        issue,
        initiator=initiator,
        filled_fields=issues_service.filled_fields_for(issue),
    )
    for item in available:
        if item.transition.name == transition_name:
            return item.transition.id
    names = ", ".join(sorted(item.transition.name for item in available)) or "none"
    raise LookupError(
        f"demo seeding expects transition {transition_name!r} out of {issue.status.key!r} "
        f"in {issue.queue.key}, available: {names}"
    )
