"""Инструменты по связям: поставить и снять.

Обе задачи разрешаются здесь, а не в сценарии: модуль связей намеренно не импортирует
сценарии задач, иначе зависимость стала бы кольцевой (`app/services/links.py`). Ровно то
же самое делает роутер REST — и это не дублирование логики, а разрешение адреса, которое
у каждого интерфейса своё.

Чтения связей отдельным инструментом нет: они приезжают в пакете преемника `get_task`
вместе со статусом задачи на другой стороне. Отдельный инструмент означал бы второй вызов
ради того, что агент получает первым.
"""

from app.mcp import views
from app.mcp.arguments import (
    IdempotencyKeyArg,
    LinkKindArg,
    OtherTaskKeyArg,
    TaskKeyArg,
)
from app.mcp.idempotency import Once
from app.mcp.toolset import FILING, Toolset
from app.services import case as case_service
from app.services import links as links_service
from app.services import tasks as tasks_service


def register(tools: Toolset) -> None:
    """Объявляет инструменты набора `task` по связям."""
    runtime = tools.runtime

    @tools.tool(annotations=FILING, creating=True)
    async def link(
        key: TaskKeyArg,
        kind: LinkKindArg,
        other: OtherTaskKeyArg,
        idempotency_key: IdempotencyKeyArg = None,
    ) -> views.LinkFilingView:
        """Связывает две задачи и подшивает `link_added` в дела обеих; обе записи
        сразу видны в ленте и человеку в интерфейсе.

        Вид называет роль задачи из `key`: `kind="blocks"` означает «`key` блокирует
        `other`», и в карточке `other` та же связь показана как `blocked_by`. Связь
        хранится один раз, поэтому повтор с другой стороны — отказ, а не вторая связь.

        Родитель и ребёнок заводятся этим же вызовом (`kind="parent"` — «`key` родитель
        `other`»), а в карточке `get_task` видны полями `parent` и `children`, не в
        `links`. Родитель у задачи один, детей сколько угодно: второй родитель — отказ
        `task_has_parent`, нынешний назван в `details.parent`.

        Незакрытый блокер поднимает у заблокированной задачи признак `blocked` и
        закрывает ей вход в `in_progress` отказом `task_blocked`.

        С закрытой задачей (`done`, `cancelled`) ставится только `relates` — им и
        связывают её с продолжением, выросшим из неё. `parent` и `blocks` у закрытой
        задачи отклоняются: они меняли бы смысл уже случившегося.

        Ответ короткий: `key`, номер записи `link_added` в его деле и номер той же
        записи в деле `other`. Вид и обе задачи вызывающий уже прислал сам; карточку
        `other` целиком, если она вдруг нужна, отдаёт `get_task`.
        """
        async with runtime.call() as (session, actor):
            # Ключи разрешаются до занятия ключа идемпотентности: вызов, отклонённый до
            # работы, не должен его тратить.
            task = await tasks_service.get_task(session, key)
            other_task = await tasks_service.get_task(session, other)

            async def add() -> views.LinkFilingView:
                await links_service.add_link(session, task, other_task, actor=actor, kind=kind)
                # Номера читаются из обоих дел, а не протаскиваются через `add_link`
                # (`docs/notes/mcp.md`): под общей блокировкой изменений последняя
                # запись каждого дела — только что подшитый `link_added`.
                entry = await case_service.latest_entry_no(session, task, actor=actor)
                other_entry = await case_service.latest_entry_no(session, other_task, actor=actor)
                return views.LinkFilingView(key=task.key, entry=entry, other_entry=other_entry)

            return await Once.of(link, session, actor, idempotency_key).run(
                result=views.LinkFilingView,
                request={"task": task.key, "kind": kind, "other": other_task.key},
                build=add,
            )

    @tools.tool(annotations=FILING)
    async def unlink(
        key: TaskKeyArg, kind: LinkKindArg, other: OtherTaskKeyArg
    ) -> views.LinkFilingView:
        """Снимает связь и подшивает `link_removed` в дела обеих задач.

        Снять можно с любой стороны и любым её именем: «снять с `TRK-1` связь `blocks` с
        `TRK-7`» и «снять с `TRK-7` связь `blocked_by` с `TRK-1`» — это одна и та же
        строка. У закрытой задачи не снимаются `parent` и `blocks`, `relates` снимается.

        Ответ короткий: `key`, номер записи `link_removed` в его деле и номер той же
        записи в деле `other`.
        """
        async with runtime.call() as (session, actor):
            task = await tasks_service.get_task(session, key)
            other_task = await tasks_service.get_task(session, other)
            await links_service.remove_link(session, task, other_task, actor=actor, kind=kind)
            entry = await case_service.latest_entry_no(session, task, actor=actor)
            other_entry = await case_service.latest_entry_no(session, other_task, actor=actor)
            return views.LinkFilingView(key=task.key, entry=entry, other_entry=other_entry)
