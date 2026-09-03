"""Схема автора действия — одна на весь API.

Автор приходит в ответе везде, где что-то было сделано: в реестрах фундамента это «кем
заведено», дальше — автор записи дела, перехода и связи. Схема одна и та же, чтобы
фронтенд рисовал подпись одним компонентом, а не разбирал три похожих объекта.
"""

from pydantic import BaseModel, ConfigDict, Field

from app.domain.authors import AuthorKind


class AuthorRead(BaseModel):
    """Кто сделал действие: род и подпись.

    Подпись пуста только у рода `tracker` — так подписано то, что трекер сделал сам.
    У человека и агента это имя участника, у временного агента — его метка из заголовка
    `X-Actor-Label`; отличить одно от другого по подписи нельзя намеренно: читающему
    дело важно, кто говорит, а не как он аутентифицировался.
    """

    model_config = ConfigDict(from_attributes=True)

    kind: AuthorKind = Field(examples=[AuthorKind.AGENT])
    signature: str | None = Field(
        default=None,
        examples=["release_bot"],
        description="Participant name or temporary agent label; null for the tracker itself",
    )
