"""Части итога, общие для `add_conclusion` и `close_discussion`: решено, заменено, открыто.

Описание части одно на оба инструмента, как у частей сводки (`app/mcp/tools/case/
arguments.py`): вторая копия разошлась бы с первой при первой правке. Пустую часть
отвергает домен (`entry_fields_invalid` с именем поля), а не схема — по правилу
`app/mcp/arguments.py` «границы — домену».
"""

from typing import Annotated

from pydantic import Field

ConclusionDecidedArg = Annotated[
    str,
    Field(
        description=(
            "What is decided, each line with a reference to the entry it follows from "
            "(`TRK~7#4`), or `nothing`. Its first line becomes the entry title"
        )
    ),
]

ConclusionSupersededArg = Annotated[
    str,
    Field(
        description=(
            "Which earlier decision, of this discussion or elsewhere, a later answer "
            "replaced, with references to both, or `nothing`"
        )
    ),
]

ConclusionOpenArg = Annotated[
    str,
    Field(description="What is still undecided, with references, or `nothing`"),
]
