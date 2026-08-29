"""Контекст выполнения правила: что правилу видно и что ему разрешено делать.

Правило получает один объект и через него делает всё. Причина не в удобстве: набор
действий обязан быть **закрытым и наблюдаемым**. Закрытым — потому что правило, которое
пишет в базу напрямую, обходит проверки воркфлоу, историю задачи и шину событий.
Наблюдаемым — потому что журнал срабатываний должен отвечать не только «сработало», но и
«что именно сделало», а собрать это можно лишь там, где действия проходят.

Поэтому каждое действие здесь — тонкая обёртка над тем же сценарием из `services`,
который зовут REST и MCP, плюс запись в список выполненных действий. Своей логики у
обёрток нет и быть не должно: как только она появится, автоматика начнёт вести себя не
так, как тот же запрос от человека.

## Условие проверяется по событию, действие выполняется над строкой

Это контракт движка, а не совет по стилю. Триггер подписан на **изменение**, и отвечать
он обязан на вопрос «что произошло», а не «как обстоят дела сейчас». Между этими двумя
вопросами стоит outbox: правило видит событие в другой транзакции и другом процессе,
спустя неизвестное время после того, как изменение случилось.

Пока воркер разбирает очередь по одному событию сразу, разницы не видно — строка задачи
совпадает со снимком в событии, и условие, написанное по `ctx.target`, работает. Стоит
событиям накопиться (воркер отстал, стартовал позже, разбирает пачку), и `ctx.target`
показывает состояние на момент **обработки**: каждое накопленное событие проходит
условие, истинное для последнего, и правило срабатывает столько раз, сколько событий
успело накопиться. Три перехода эпика подряд дали три одинаковых комментария там, где
ожидался один.

Отсюда разделение, обязательное для каждого триггера:

- **условие** — по нагрузке события: `status_change()`, `entered_category()`,
  `change_of()`, `changed_fields()`, `payload`;
- **действие** — над актуальной строкой: `target`, `parent()`, `children()`, и все
  методы раздела «Действия».

Обе половины верны каждая для своего: решать надо по тому, что случилось, а менять — то,
что есть сейчас. Правило, закрывающее подзадачи, спрашивает у события «родителя
перевели в `done`?» и закрывает те подзадачи, которые открыты **на момент действия**, а
не те, что были открыты на момент события.

У автодействия и макроса события нет вовсе (`event is None`): их «условие» — это отбор
задач фильтром и текущее состояние строки, и читать её там правильно. Контракт касается
только триггеров.

## Правило выполняется от системного актора, но помнит настоящего инициатора

`ctx.actor` — системный актор, от его имени идут изменения и он же стоит автором в
истории задачи. `ctx.initiator` — тот, чьё действие породило событие. Второй нужен и
самим правилам («не трогать задачу, если её только что тронул человек»), и журналу:
запись «правило X, запущено из-за действия актора Y» собирается из этой пары.

## Пропуск — это исключение, а не возвращаемое значение

`ctx.skip(...)` бросает `RuleSkipped`. Возврат значения заставлял бы каждое правило
дотаскивать его до конца функции через все ветки, а вложенный вызов (`ctx.skip` внутри
цикла) не смог бы прервать работу вовсе. Исключение прерывает ровно там, где вызвано, и
движок превращает его в строку журнала со статусом `skipped`.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.automation.registry import RuleAction, RuleDefinition
from app.core.errors import NotFoundError
from app.core.sentinels import UNSET
from app.db.models.actor import Actor
from app.db.models.automation import AutomationRule
from app.db.models.catalog import IssueType, Resolution, Status
from app.db.models.checklist import ChecklistItem
from app.db.models.comment import Comment
from app.db.models.issue import Issue
from app.db.models.notification import Notification
from app.db.models.webhook import WebhookDelivery
from app.db.repositories import AutomationRunRepository, IssueLinkRepository
from app.domain.automation import SkipReason
from app.domain.catalogs import CatalogKind, StatusCategory
from app.domain.issues import IssueField
from app.domain.links import LinkType
from app.services import actors as actors_service
from app.services import checklists as checklists_service
from app.services import comments as comments_service
from app.services import issues as issues_service
from app.services import links as links_service
from app.services import notifications as notifications_service
from app.services import queues as queues_service
from app.services import webhooks as webhooks_service
from app.services import workflow as workflow_service
from app.services.event_bus import EventEnvelope


class RuleSkipped(Exception):
    """Правило решило ничего не делать. Не ошибка: движок пишет `skipped`, а не `failed`.

    Имя без суффикса `Error` намеренно: это управление потоком, а не сбой, и в журнале
    эти два исхода обязаны различаться. Слить их значило бы получить журнал, в котором
    нормальная работа неотличима от поломки.
    """

    def __init__(self, reason: str, details: dict[str, Any] | None = None) -> None:
        self.reason = reason
        self.details = details or {}
        super().__init__(reason)


@dataclass(frozen=True, slots=True)
class StatusChange:
    """Смена статуса, которую описывает событие: что было и что стало.

    Записи справочника, а не ссылки из нагрузки: категория — свойство справочника, и
    ради неё вопрос и задаётся. Разрешение ссылки — единственное чтение базы, которое
    условию приходится делать, и оно не то же самое, что чтение состояния задачи:
    статусы описывают процесс, а не то, где задача находится сейчас.

    `before` — `None`, если прежний статус успел исчезнуть из справочника, пока событие
    лежало в очереди. Удалить статус можно только после того, как с него увели все
    задачи, так что случай редкий, но законный. Категорию такого статуса узнать неоткуда,
    и `entered` считает его «не той категорией»: пропустить настоящий переход в `done`
    хуже, чем изредка отработать на переходе внутри категории.
    """

    before: Status | None
    after: Status

    def entered(self, category: StatusCategory) -> bool:
        """Событие ввело задачу в категорию: до перехода её там не было.

        Именно «ввело», а не «привело»: переход между двумя статусами одной категории
        (`closed → released`, оба `done`) условие не проходит. Иначе правило,
        реагирующее на закрытие, отработало бы второй раз на задаче, которая и так была
        закрыта, — то есть вернулся бы ровно тот дубль, ради которого вопрос и заведён.

        Правилу, которому важен любой переход внутри категории, хватит `status_change()`:
        обе записи справочника у него на руках.
        """
        return self.after.category is category and (
            self.before is None or self.before.category is not category
        )


@dataclass(slots=True)
class RuleContext:
    """Всё, что видит и умеет правило во время одного срабатывания.

    Собирается движком, правилом не создаётся. Изменяемый только в одном месте — список
    выполненных действий; остальное задаётся при сборке и не меняется.
    """

    session: AsyncSession
    definition: RuleDefinition
    rule: AutomationRule
    run_id: uuid.UUID
    #: Глубина цепочки, которую получат события этого срабатывания.
    depth: int
    #: Системный актор: от его имени идут все изменения правила.
    actor: Actor
    #: Тот, чьё действие привело к запуску. У автодействия — тот же системный актор:
    #: расписание никто не инициирует.
    initiator: Actor
    params: BaseModel
    #: Задача, по которой работает правило. `None` у триггера на событие, не связанное
    #: с задачей (доска, массовый перенос): такое правило работает с событием.
    issue: Issue | None = None
    #: Событие, вызвавшее срабатывание. `None` у автодействия и макроса.
    event: EventEnvelope | None = None
    actions: list[RuleAction] = field(default_factory=list)

    # --- Чтение --------------------------------------------------------------------

    @property
    def target(self) -> Issue:
        """Задача правила — **живая строка из базы**, а не снимок из события.

        Отсюда единственное верное её применение у триггера: действие. Условие по ней
        писать нельзя (см. «Условие проверяется по событию» в шапке модуля) — она
        отвечает за момент обработки события, а не за тот, который событие описывает.
        Действию же нужна именно она: менять надо то, что есть сейчас.

        Обращение при отсутствии задачи — ошибка программиста, не данных. Отдельное
        свойство рядом с необязательным полем нужно ровно затем, чтобы правило,
        написанное для задачи, падало понятной ошибкой, а не `AttributeError` на `None`
        где-то в третьей строке действия.
        """
        if self.issue is None:
            raise RuntimeError(
                f"Rule {self.definition.key!r} asked for an issue, but the run has none "
                f"(event {'-' if self.event is None else self.event.event_type})"
            )
        return self.issue

    @property
    def payload(self) -> dict[str, Any]:
        """Полезная нагрузка события. Пустой словарь, если срабатывание не от события."""
        return {} if self.event is None else self.event.payload

    def changed_fields(self) -> frozenset[str]:
        """Имена полей, изменённых событием: `status`, `assignee`, `TRK.severity`.

        Смотреть надо именно сюда, а не только на тип события: `issue.status_changed`
        может нести вместе со статусом ещё и смену исполнителя, а `issue.updated` —
        любое поле, включая кастомное.
        """
        return frozenset(self.payload.get("fields", ()))

    def change_of(self, field_name: str) -> dict[str, Any] | None:
        """Запись «было → стало» по одному полю или `None`, если поле не менялось.

        Значения — те же, что в истории задачи: ссылки справочников (`TRK.closed`),
        ключи акторов, время строкой. Записи справочника из них не выводятся — для
        статуса это делает `status_change()`.
        """
        for change in self.payload.get("changes", ()):
            if change.get("field") == field_name:
                return change
        return None

    async def status_change(self) -> StatusChange | None:
        """Смена статуса, которую описывает событие, — со ссылками, разрешёнными в записи.

        `None` означает «утверждать нечего» и покрывает два случая сразу: событие
        статуса не меняло **или** новый статус успел исчезнуть из справочника, пока
        событие лежало в очереди. Для условия это один и тот же ответ — «не могу
        сказать, что событие перевело задачу куда-то», — и разделять их значило бы
        обязать каждое правило обрабатывать вторую ветку, ничего не выигрывая.

        Падать на исчезнувшем статусе нельзя: удаление статуса — законная операция
        администратора (перед ним задачи с этого статуса уводят), а правило,
        разбирающее старое событие, свалилось бы из-за неё в журнал со статусом
        `failed`. Массовый перенос задач между статусами сюда не попадает вовсе — он
        приходит одним событием `status.issues_moved` без списка изменений.
        """
        change = self.change_of(IssueField.STATUS.value)
        if change is None:
            return None
        after = await self._status_or_none(change.get("after"))
        if after is None:
            return None
        return StatusChange(before=await self._status_or_none(change.get("before")), after=after)

    async def entered_category(self, category: StatusCategory) -> bool:
        """Событие перевело задачу в эту категорию статусов. Условие триггера — одним вызовом.

        Категория, а не ключ статуса: команда вправе назвать закрывающий статус как
        угодно, и правило обязано работать в очереди, где он называется `released`.

        Отдельный метод, а не строка в каждом правиле, — потому что достать категорию из
        события нетривиально: в нагрузке лежит ссылка, категория живёт в справочнике, а
        исчезнувший статус не должен ронять правило. Оставленный правилам, этот вопрос
        решался бы в каждом по-своему, и половина решений читала бы `ctx.target`.
        """
        change = await self.status_change()
        return change is not None and change.entered(category)

    async def _status_or_none(self, ref: Any) -> Status | None:
        """Ссылка из нагрузки в запись справочника; `None`, если такой записи уже нет."""
        if not isinstance(ref, str):
            return None
        try:
            return await self.status(ref)
        except NotFoundError:
            return None

    async def parent(self) -> Issue | None:
        """Родительская задача или `None`. Родитель у задачи ровно один."""
        link = await IssueLinkRepository(self.session).parent_link(self.target.id)
        return None if link is None else link.target

    async def children(self) -> list[Issue]:
        """Прямые подзадачи. Только один уровень: дерево целиком — `links_service`."""
        links = await IssueLinkRepository(self.session).children([self.target.id])
        return [link.source for link in links]

    async def checklist(self, issue: Issue | None = None) -> list[ChecklistItem]:
        """Чеклист задачи целиком, по порядку. Число пунктов ограничено доменом."""
        return await checklists_service.list_items(
            self.session,
            issue or self.target,
            initiator=self.actor,
        )

    async def last_run_at(self, issue: Issue | None = None) -> datetime | None:
        """Когда это правило в последний раз что-то сделало с задачей.

        Нужно правилам, которые действуют, не меняя строку задачи: комментарий не
        двигает `updated_at`, поэтому фильтр «без движения 7 дней» остаётся истинным и
        на следующем тике расписания. Без этого вопроса такое правило комментировало бы
        одну и ту же задачу каждый тик.
        """
        target = issue or self.target
        return await AutomationRunRepository(self.session).last_success_at(
            rule_id=self.rule.id,
            issue_id=target.id,
        )

    # --- Разрешение ссылок ----------------------------------------------------------

    async def status(self, ref: str) -> Status:
        """Статус по ссылке (`open`, `TRK.open`). Ссылка, а не имя: имя редактируемо."""
        entry = await queues_service.resolve_catalog_ref(
            self.session,
            CatalogKind.STATUS,
            ref,
            initiator=self.actor,
        )
        assert isinstance(entry, Status)
        return entry

    async def resolution(self, ref: str) -> Resolution:
        entry = await queues_service.resolve_catalog_ref(
            self.session,
            CatalogKind.RESOLUTION,
            ref,
            initiator=self.actor,
        )
        assert isinstance(entry, Resolution)
        return entry

    async def issue_type(self, ref: str) -> IssueType:
        entry = await queues_service.resolve_catalog_ref(
            self.session,
            CatalogKind.ISSUE_TYPE,
            ref,
            initiator=self.actor,
        )
        assert isinstance(entry, IssueType)
        return entry

    async def actor_by_key(self, key: str) -> Actor:
        return await actors_service.get_actor_by_key(self.session, key)

    async def issue_by_key(self, key: str) -> Issue:
        return await issues_service.get_issue_by_key(self.session, key)

    # --- Управление ходом -----------------------------------------------------------

    def skip(self, reason: str = SkipReason.CONDITION_NOT_MET, **details: Any) -> None:
        """Прерывает правило: делать нечего. Возвращаемый тип `None` — она не возвращается.

        Аннотация не врёт, а описывает вызывающую сторону: `ctx.skip(...)` пишется как
        оператор, а не как значение. Тип `NoReturn` заставил бы каждое `if ...:
        ctx.skip()` выглядеть как конец функции и сбивал бы проверку недостижимого кода
        там, где после пропуска идут другие ветки.
        """
        raise RuleSkipped(str(reason), details)

    def note(self, action: str, target: str | None = None, **details: Any) -> None:
        """Записывает в журнал действие, выполненное не через контекст.

        Нужна редко и намеренно неудобна: если правило что-то делает мимо действий
        контекста, это обязано быть видно в журнале. Совсем не делать этого нельзя —
        останутся правила, которые считают и решают, ничего не меняя, а их вывод тоже
        полезно видеть.
        """
        self.actions.append(RuleAction(action=action, target=target, details=details))

    # --- Действия -------------------------------------------------------------------

    async def update(
        self,
        issue: Issue | None = None,
        **changes: Any,
    ) -> issues_service.IssueMutation:
        """Меняет поля задачи через единую точку изменений.

        Именованные аргументы — поля `IssueChanges`: `summary`, `priority`, `assignee`,
        `deadline`, `tags`, `values`, `project`. Непереданное поле не трогается, `None`
        очищает то, что очищается.
        """
        target = issue or self.target
        mutation = await issues_service.update_issue(
            self.session,
            target,
            initiator=self.actor,
            changes=issues_service.IssueChanges(**changes),
        )
        if mutation.changed:
            self.actions.append(
                RuleAction(
                    action="update",
                    target=target.key,
                    details={"fields": [change.field for change in mutation.changes]},
                )
            )
        return mutation

    async def set_status(
        self,
        status: Status | str,
        *,
        issue: Issue | None = None,
        resolution: Resolution | str | None = UNSET,
    ) -> issues_service.IssueMutation:
        """Переводит задачу в статус — через проверку воркфлоу, как обычный запрос.

        Ребра в графе процесса нет — будет `transition_not_allowed`, и правило упадёт с
        этой ошибкой в журнале. Так и задумано: правило, которому разрешили ходить мимо
        воркфлоу, обесценил бы сам воркфлоу, а «тихо не сделал» скрыло бы расхождение
        между процессом и правилом до момента, когда его уже не найти.
        """
        target = issue or self.target
        target_status = status if isinstance(status, Status) else await self.status(status)
        changes: dict[str, Any] = {"status": target_status}
        if resolution is not UNSET:
            changes["resolution"] = (
                resolution
                if resolution is None or isinstance(resolution, Resolution)
                else await self.resolution(resolution)
            )
        before = target.status.ref
        mutation = await issues_service.apply_issue_changes(
            self.session,
            target,
            initiator=self.actor,
            changes=issues_service.IssueChanges(**changes),
            action="issue.transition",
        )
        if mutation.changed:
            self.actions.append(
                RuleAction(
                    action="set_status",
                    target=target.key,
                    details={"from": before, "to": target_status.ref},
                )
            )
        return mutation

    async def transition_to_category(
        self,
        category: StatusCategory,
        *,
        issue: Issue | None = None,
        resolution: Resolution | str | None = UNSET,
    ) -> issues_service.IssueMutation | None:
        """Переводит задачу в первый доступный статус нужной категории.

        Нужна правилам, которые рассуждают категориями, а не ключами: «закрыть
        подзадачи» обязано работать в очереди, где закрывающий статус называется
        `released`, а не `closed`. Возвращает `None`, если подходящего перехода в графе
        процесса нет, — это не ошибка правила, а особенность конкретного процесса, и
        решать, что с этим делать, должно само правило.

        Доступность считает движок воркфлоу с учётом требуемых полей, и считает её по
        **будущему** состоянию задачи: переданная резолюция уже входит в набор
        заполненных полей. Иначе закрывающий переход, который требует резолюции, всегда
        оказывался бы недоступным — а правило именно её и передаёт.
        """
        target = issue or self.target
        resolved = (
            resolution
            if resolution is UNSET or resolution is None or isinstance(resolution, Resolution)
            else await self.resolution(resolution)
        )
        planned = (
            issues_service.IssueChanges()
            if resolved is UNSET
            else issues_service.IssueChanges(resolution=resolved)
        )
        candidates = await workflow_service.available_transitions(
            self.session,
            target,
            initiator=self.actor,
            filled_fields=issues_service.filled_fields_for(target, planned),
        )
        for candidate in candidates:
            if not candidate.is_available:
                continue
            if candidate.transition.to_status.category is category:
                return await self.set_status(
                    candidate.transition.to_status,
                    issue=target,
                    resolution=resolved,
                )
        return None

    async def assign(
        self,
        assignee: Actor | str | None,
        *,
        issue: Issue | None = None,
    ) -> issues_service.IssueMutation:
        """Назначает исполнителя или снимает его, если передан `None`."""
        target = issue or self.target
        actor = (
            assignee
            if assignee is None or isinstance(assignee, Actor)
            else await self.actor_by_key(assignee)
        )
        mutation = await issues_service.assign_issue(
            self.session,
            target,
            initiator=self.actor,
            assignee=actor,
        )
        if mutation.changed:
            self.actions.append(
                RuleAction(
                    action="assign",
                    target=target.key,
                    details={"assignee": None if actor is None else actor.key},
                )
            )
        return mutation

    async def comment(self, body: str, *, issue: Issue | None = None) -> Comment:
        """Пишет комментарий от системного актора.

        Обычный `comment.created`, а не особый тип: движок уведомлений обязан донести
        его до людей — это и есть главный способ, которым автоматика с ними
        разговаривает.
        """
        target = issue or self.target
        created = await comments_service.add_comment(
            self.session,
            target,
            initiator=self.actor,
            body=body,
        )
        self.actions.append(
            RuleAction(action="comment", target=target.key, details={"comment": str(created.id)})
        )
        return created

    async def notify(
        self,
        actor: Actor | str,
        body: str,
        *,
        issue: Issue | None = None,
        **details: Any,
    ) -> Notification | None:
        """Кладёт сообщение в инбокс актора.

        Второй способ правила заговорить с человеком, кроме комментария, и они не
        взаимозаменяемы. Комментарий виден всем, кто читает задачу, и остаётся в её
        обсуждении; уведомление адресовано одному и живёт в его ленте. «Дедлайн
        завтра» — это уведомление, «задача закрыта по правилу X» — комментарий.

        Своей логики адресации здесь нет: правило называет актора, а решают всё
        сценарий инбокса и подписки. Системному актору сообщение не уходит — правила
        выполняются от его имени, и его инбокс никто не читает; такой вызов
        записывается в журнал срабатываний с пометкой `skipped`, а не теряется молча.
        """
        target = actor if isinstance(actor, Actor) else await self.actor_by_key(actor)
        subject = issue or self.issue
        notification = await notifications_service.notify_actor(
            self.session,
            actor=target,
            body=body,
            details=details or None,
            issue=subject,
        )
        self.actions.append(
            RuleAction(
                action="notify",
                target=target.key,
                details={"notification": str(notification.id)}
                if notification is not None
                else {"skipped": "system_actor"},
            )
        )
        return notification

    async def webhook(
        self,
        subscription: str,
        body: str,
        *,
        issue: Issue | None = None,
        **details: Any,
    ) -> WebhookDelivery | None:
        """Ставит задание на доставку вебхука по имени подписки.

        Третий способ правила заговорить с внешним миром, и единственный, который
        уходит **за пределы трекера**: комментарий виден читателям задачи, уведомление —
        одному актору, вебхук дёргает чужую систему (бота, CI, скрипт).

        Ставит **задание**, а не делает HTTP-запрос. Синхронный вызов задержал бы
        обработку события на таймаут мёртвого адреса и уронил бы правило вместе со всей
        его работой; отправкой занимается отдельный процесс (`app/webhooks.py`).
        Отсюда следствие, которое правило обязано учитывать: возврат из этого метода
        означает «вызов поставлен в очередь», а не «получатель его получил».

        Подписка адресуется **именем**, а не идентификатором: имена настраивают люди в
        параметрах правила, и UUID в них нечитаем. Несуществующее имя — ошибка правила
        (опечатка в параметрах), а выключенная подписка или её фильтр типов — пропуск с
        пометкой в журнале: чужая настройка не должна ронять правило.
        """
        target = await webhooks_service.get_subscription_by_name(
            self.session,
            subscription,
            initiator=self.actor,
        )
        subject = issue or self.issue
        outcome = await webhooks_service.enqueue_direct(
            self.session,
            target,
            initiator=self.actor,
            body=body,
            details=details or None,
            issue=subject,
            rule_key=self.definition.key,
        )
        self.actions.append(
            RuleAction(
                action="webhook",
                target=target.name,
                details={"delivery": str(outcome.delivery.id)}
                if outcome.delivery is not None
                else {"skipped": outcome.skipped},
            )
        )
        return outcome.delivery

    async def add_checklist_item(
        self,
        text: str,
        *,
        issue: Issue | None = None,
        assignee: Actor | str | None = None,
        deadline: datetime | None = None,
    ) -> ChecklistItem:
        """Добавляет пункт в конец чеклиста задачи."""
        target = issue or self.target
        actor = (
            assignee
            if assignee is None or isinstance(assignee, Actor)
            else await self.actor_by_key(assignee)
        )
        item = await checklists_service.add_item(
            self.session,
            target,
            initiator=self.actor,
            text=text,
            assignee=actor,
            deadline=deadline,
        )
        self.actions.append(
            RuleAction(
                action="add_checklist_item",
                target=target.key,
                details={"item": str(item.id)},
            )
        )
        return item

    async def link(
        self,
        target: Issue | str,
        link_type: LinkType,
        *,
        issue: Issue | None = None,
    ) -> None:
        """Связывает задачи. Читается как «`issue` <тип> `target`»."""
        source = issue or self.target
        other = target if isinstance(target, Issue) else await self.issue_by_key(target)
        await links_service.create_link(
            self.session,
            initiator=self.actor,
            source=source,
            link_type=link_type,
            target=other,
        )
        self.actions.append(
            RuleAction(
                action="link",
                target=source.key,
                details={"type": link_type.value, "issue": other.key},
            )
        )

    async def create_subtask(
        self,
        summary: str,
        *,
        parent: Issue | None = None,
        **fields: Any,
    ) -> Issue:
        """Заводит подзадачу в очереди родителя и подчиняет её ему.

        Два шага, а не один: связь `subtask_of` заводится отдельным сценарием, потому
        что она — такая же связь, как остальные, и её правила иерархии (цикл, второй
        родитель, эпик без родителя) проверяются в одном месте.
        """
        target = parent or self.target
        child = await issues_service.create_issue(
            self.session,
            initiator=self.actor,
            queue=fields.pop("queue", target.queue),
            summary=summary,
            **fields,
        )
        await links_service.create_link(
            self.session,
            initiator=self.actor,
            source=child,
            link_type=LinkType.SUBTASK_OF,
            target=target,
        )
        self.actions.append(
            RuleAction(action="create_subtask", target=target.key, details={"issue": child.key})
        )
        return child

    async def reparent(self, child: Issue, new_parent: Issue) -> None:
        """Переподчиняет задачу другому родителю: снимает прежнюю связь и заводит новую.

        Два шага обязательны, и это не деталь реализации. Родитель у задачи ровно один,
        и попытка завести второго даёт `link_parent_exists`, а не переносит задачу —
        правило, сделавшее только второй шаг, упало бы на ровном месте.
        """
        repository = IssueLinkRepository(self.session)
        existing = await repository.parent_link(child.id)
        if existing is not None:
            if existing.target_id == new_parent.id:
                return
            await links_service.delete_link(self.session, existing, initiator=self.actor)
        await links_service.create_link(
            self.session,
            initiator=self.actor,
            source=child,
            link_type=LinkType.SUBTASK_OF,
            target=new_parent,
        )
        self.actions.append(
            RuleAction(
                action="reparent",
                target=child.key,
                details={"parent": new_parent.key},
            )
        )


def action_payload(actions: Sequence[RuleAction]) -> list[dict[str, Any]]:
    """Список выполненных действий в вид для JSONB журнала."""
    return [item.to_payload() for item in actions]
