"""Макрос: оформить задачу как релизную.

Запускается человеком или агентом для конкретной задачи —
`POST /api/v1/automation/rules/prepare_release/run`. Расписания и подписки на события у
макроса нет: он делает то, что иначе пришлось бы делать четырьмя запросами подряд.

Параметры можно переопределить прямо в вызове: сохранённые в правиле значения — это
умолчание для установки, а переданные в запросе действуют только на этот запуск. Так
один макрос обслуживает и «как обычно», и «в этот раз с другим чеклистом».

Состояние задачи (`ctx.target.tags`, `priority`, `assignee`) макрос читает по праву:
контракт «условие — по событию» касается триггеров, а у макроса события нет — он
запускается по конкретной задаче и работает с ней такой, какая она в момент вызова.
"""

from pydantic import BaseModel, Field

from app.automation.context import RuleContext
from app.automation.registry import rule
from app.domain.automation import RuleKind
from app.domain.issues import IssuePriority


class Params(BaseModel):
    """Настройки макроса."""

    model_config = {"extra": "forbid"}

    tags: list[str] = Field(
        default_factory=lambda: ["release"],
        max_length=16,
        description="Tags added to the issue; existing tags are kept",
    )
    priority: IssuePriority | None = Field(
        default=IssuePriority.BLOCKER,
        description="Priority to set, or null to leave it as is",
    )
    checklist: list[str] = Field(
        default_factory=lambda: [
            "Собрать список изменений",
            "Прогнать регресс",  # noqa: RUF001
            "Обновить документацию",
            "Выкатить и проверить на проде",
        ],
        max_length=32,
        description="Checklist items appended to the issue",
    )
    assignee: str | None = Field(
        default=None,
        description="Actor key to assign if the issue has no assignee yet",
    )


@rule(
    key="prepare_release",
    name="Оформить как релизную задачу",
    kind=RuleKind.MACRO,
    params=Params,
    description=(
        "Tags the issue as a release, raises its priority, appends a release checklist "
        "and assigns it if nobody is on it yet"
    ),
)
async def prepare_release(ctx: RuleContext) -> None:
    """Приводит задачу к виду релизной за один вызов."""
    params = ctx.params
    assert isinstance(params, Params)

    issue = ctx.target
    changes: dict[str, object] = {}
    if params.tags:
        # Теги дописываются, а не заменяются: макрос оформляет задачу, а не переписывает
        # её. Единая точка изменений принимает **весь** набор тегов, поэтому склейка
        # делается здесь; повторы снимет нормализация в домене.
        changes["tags"] = [*issue.tags, *params.tags]
    if params.priority is not None and issue.priority is not params.priority:
        changes["priority"] = params.priority
    if changes:
        await ctx.update(**changes)

    if params.assignee is not None and issue.assignee is None:
        await ctx.assign(params.assignee)

    existing = {item.text for item in await ctx.checklist()}
    for text in params.checklist:
        # Повторный запуск макроса не должен удваивать чеклист: у пункта нет ключа, и
        # различить «добавили второй раз» от «так и было» потом уже нечем.
        if text not in existing:
            await ctx.add_checklist_item(text)
