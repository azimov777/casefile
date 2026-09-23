"""Инструменты по реестрам: очереди и участники.

Чтение открыто набору `task` — оно часть рабочего цикла: без списка очередей агент с
чистым контекстом не найдёт, где вообще лежат задачи, без описания очереди не знает
общего контекста её задач, без реестра участников ему некому адресовать вопрос.
Запись требует набора `main`: заводить очереди и регистрировать участников — управление
установкой, а не работа над задачей.

Выпуска токенов здесь нет и не будет: выдача доступов остаётся за человеком и идёт
только через REST (`CONCEPT.md`, 5.2).
"""

from app.domain.tokens import TokenScope
from app.mcp import views
from app.mcp.arguments import (
    CursorArg,
    IdempotencyKeyArg,
    LimitArg,
    ParticipantDescriptionArg,
    ParticipantKindArg,
    ParticipantNameArg,
    QueueDescriptionArg,
    QueueDescriptionChangeArg,
    QueueKeyArg,
    QueueTitleArg,
    QueueTitleChangeArg,
)
from app.mcp.idempotency import Once
from app.mcp.toolset import FILING, OVERWRITING_UPDATE, READ_ONLY, Toolset
from app.services import participants as participants_service
from app.services import queues as queues_service


def register(tools: Toolset) -> None:
    """Объявляет инструменты по реестрам: чтение — набору `task`, запись — `main`."""
    runtime = tools.runtime
    settings = tools.settings

    @tools.tool(annotations=READ_ONLY)
    async def get_queue(key: QueueKeyArg) -> views.QueueView:
        """Очередь с описанием — общим контекстом всех её задач: где лежит код, на какие
        документы смотреть, чего не делать.

        В карточке задачи от очереди только ключ и название; описание отдаёт этот вызов.
        """
        async with runtime.call() as (session, actor):
            return views.queue(await queues_service.read_queue(session, key, actor=actor))

    @tools.tool(annotations=READ_ONLY)
    async def list_queues(
        limit: LimitArg = None,
        cursor: CursorArg = None,
    ) -> views.PageView[views.QueueRefView]:
        """Все очереди установки: ключ и название.

        Описания здесь нет: у выбранной очереди его отдаёт `get_queue`, а в списке оно
        стоило бы контекста больше, чем сам выбор.
        """
        async with runtime.call() as (session, actor):
            page = await queues_service.list_queues(
                session, actor=actor, limit=limit or settings.mcp_page_size, cursor=cursor
            )
            return views.page(
                (views.queue_ref(item) for item in page.items),
                next_cursor=page.next_cursor,
            )

    @tools.tool(annotations=READ_ONLY)
    async def list_participants(
        limit: LimitArg = None,
        cursor: CursorArg = None,
    ) -> views.PageView[views.ParticipantView]:
        """Реестр участников: кому можно адресовать вопрос.

        Люди и постоянные агенты одним списком. Временных агентов здесь нет и быть не
        может — они не регистрируются, и адресовать их нельзя.
        """
        async with runtime.call() as (session, actor):
            page = await participants_service.list_participants(
                session, actor=actor, limit=limit or settings.mcp_page_size, cursor=cursor
            )
            return views.page(
                (views.participant(item) for item in page.items),
                next_cursor=page.next_cursor,
            )

    @tools.tool(annotations=FILING, scope=TokenScope.MAIN, creating=True)
    async def create_queue(
        key: QueueKeyArg,
        title: QueueTitleArg,
        description: QueueDescriptionArg = "",
        idempotency_key: IdempotencyKeyArg = None,
    ) -> views.QueueView:
        """Заводит очередь. Требует набора `main`.

        Ключ хранится в верхнем регистре и дальше неизменяем: он идёт в ключ каждой
        задачи очереди. В описании — общий контекст всех её задач.
        """
        async with runtime.call() as (session, actor):

            async def create() -> views.QueueView:
                return views.queue(
                    await queues_service.create_queue(
                        session, actor=actor, key=key, title=title, description=description
                    )
                )

            return await Once.of(create_queue, session, actor, idempotency_key).run(
                result=views.QueueView,
                request={"key": key, "title": title, "description": description},
                build=create,
            )

    @tools.tool(annotations=OVERWRITING_UPDATE, scope=TokenScope.MAIN)
    async def update_queue(
        key: QueueKeyArg,
        title: QueueTitleChangeArg = None,
        description: QueueDescriptionChangeArg = None,
    ) -> views.QueueView:
        """Меняет название и описание очереди. Требует набора `main`.

        Ключ не меняется никогда: он вшит в ключ каждой задачи очереди. Непереданное
        поле не трогается; осмысленного `null` ни у названия, ни у описания нет.
        """
        async with runtime.call() as (session, actor):
            queue = await queues_service.get_queue(session, key)
            return views.queue(
                await queues_service.update_queue(
                    session, queue, actor=actor, title=title, description=description
                )
            )

    @tools.tool(annotations=FILING, scope=TokenScope.MAIN, creating=True)
    async def register_participant(
        kind: ParticipantKindArg,
        name: ParticipantNameArg,
        description: ParticipantDescriptionArg = "",
        idempotency_key: IdempotencyKeyArg = None,
    ) -> views.ParticipantView:
        """Регистрирует человека или постоянного агента. Требует набора `main`.

        Имя хранится в нижнем регистре и дальше неизменяемо: оно стоит подписью в уже
        подшитых записях дела. Токен участнику выпускают через REST.
        """
        async with runtime.call() as (session, actor):

            async def create() -> views.ParticipantView:
                return views.participant(
                    await participants_service.register_participant(
                        session, actor=actor, kind=kind, name=name, description=description
                    )
                )

            return await Once.of(register_participant, session, actor, idempotency_key).run(
                result=views.ParticipantView,
                request={"kind": kind, "name": name, "description": description},
                build=create,
            )

    @tools.tool(annotations=OVERWRITING_UPDATE, scope=TokenScope.MAIN)
    async def update_participant(
        name: ParticipantNameArg,
        description: ParticipantDescriptionArg,
    ) -> views.ParticipantView:
        """Меняет описание участника. Требует набора `main`.

        Имя и род неизменяемы: имя стоит подписью в записях дела, род объясняет
        читателю, кто говорит, — переписать их задним числом значило бы переписать
        историю, которую дело обязано хранить неизменной.
        """
        async with runtime.call() as (session, actor):
            participant = await participants_service.get_participant(session, name)
            return views.participant(
                await participants_service.update_participant(
                    session, participant, actor=actor, description=description
                )
            )
