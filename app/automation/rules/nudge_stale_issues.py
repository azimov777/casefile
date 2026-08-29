"""Автодействие: задачи, которые давно не двигались.

Отбор объявлен строкой на языке запросов и вычисляется в момент запуска: `today() - 7d`
означает семь дней от сегодняшнего дня, а не от дня выкладки. Именно поэтому отбор
хранится строкой, а не разобранным фильтром.

Нужен другой набор задач — не правьте эту строку, а заведите сохранённый фильтр и
привяжите его к правилу: `PATCH /api/v1/automation/rules/nudge_stale_issues`. Фильтр
проверяется при сохранении и виден в интерфейсе, а строка в коде — нет.

## Состояние задачи здесь читается по праву

Контракт «условие — по событию, действие — по строке» касается триггеров: у них есть
событие, которое описывает конкретный момент. У автодействия события нет вовсе, а
условие — это и есть текущее состояние: отбор возвращает задачи, подходящие **сейчас**,
и спрашивать `ctx.target` про исполнителя правильно. Расхождение «состояние против
изменения» здесь невозможно, а вот повтор по одной и той же задаче — очень даже, и
защита от него ниже.

## Почему правилу нужен собственный интервал молчания

Комментарий не меняет строку задачи, поэтому `updated_at` после него остаётся прежним, и
отбор «без движения семь дней» на следующем тике снова истинен. Без проверки «когда я
трогал эту задачу в прошлый раз» правило комментировало бы одну и ту же задачу каждые
шесть часов. Ни глубина цепочки, ни лимит срабатываний тут не спасают: лимит считает
окно в минуту, а тут нужны дни.
"""

from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, Field

from app.automation.context import RuleContext
from app.automation.registry import rule
from app.domain.automation import RuleKind

#: Отбор по умолчанию. `status_category`, а не конкретный статус: правило обязано
#: работать в очереди, где статусы называются по-своему.
STALE_QUERY = "status_category: in_progress and updated_at: <= today() - 7d"


class Params(BaseModel):
    """Настройки правила."""

    model_config = {"extra": "forbid"}

    silence_days: int = Field(
        default=7,
        ge=1,
        le=365,
        description="Days to stay silent about the same issue after nudging it",
    )
    unassign: bool = Field(
        default=False,
        description="Also drop the assignee, returning the issue to the pool",
    )
    text: str = Field(
        default="Задача давно не двигалась. Она ещё в работе?",
        min_length=1,
        max_length=1000,
        description="Comment posted on a stale issue",
    )


@rule(
    key="nudge_stale_issues",
    name="Напоминание о зависших задачах",  # noqa: RUF001
    kind=RuleKind.SCHEDULED,
    schedule=timedelta(hours=6),
    query=STALE_QUERY,
    params=Params,
    description=(
        "Comments on issues that have been in progress without any change for a week, "
        "optionally dropping the assignee"
    ),
)
async def nudge_stale_issues(ctx: RuleContext) -> None:
    """Один заход по одной задаче из отбора."""
    params = ctx.params
    assert isinstance(params, Params)

    last = await ctx.last_run_at()
    if last is not None and last > datetime.now(UTC) - timedelta(days=params.silence_days):
        ctx.skip("still_silent", last_run_at=last.isoformat())

    await ctx.comment(params.text)
    if params.unassign and ctx.target.assignee is not None:
        await ctx.assign(None)
