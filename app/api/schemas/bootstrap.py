"""Схема первого экрана."""

from pydantic import BaseModel, Field

from app.api.schemas.accounts import AccountRead
from app.api.schemas.participants import ParticipantRead
from app.api.schemas.projects import ProjectRead
from app.api.schemas.tokens import CurrentTokenRead


class BootstrapRead(BaseModel):
    """Всё, что нужно интерфейсу до первой отрисовки, и ничего сверх этого."""

    participant: ParticipantRead | None = Field(
        default=None,
        description=(
            "Participant behind the token; null for a shared agent token, whose author "
            "is a temporary agent and has no registry entry"
        ),
    )
    account: AccountRead | None = Field(
        default=None,
        description=(
            "Account of that participant: its email and the administrator flag, which "
            "opens managing accounts. Null for agents and for people who have no account"
        ),
    )
    token: CurrentTokenRead = Field(
        description=(
            "The token this request was made with: its `id` and scope. Present for every "
            "token, a shared agent one included, where `participant` is null"
        ),
    )
    projects: list[ProjectRead] = Field(
        description=(
            "Projects of the installation, one page capped at the common page ceiling. "
            "An installation with more projects than that pages `GET /api/v1/projects`"
        ),
    )
    open_questions: int = Field(
        examples=[3],
        description=(
            "Questions with no answer yet addressed to `participant`. Zero with a shared "
            "agent token: a temporary agent cannot be addressed at all"
        ),
    )
