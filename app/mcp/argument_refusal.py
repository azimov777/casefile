"""Отказ разбора аргументов называет принимаемые аргументы и место вложенного поля.

Разбор аргументов инструмента делает SDK до кода инструмента (`Tool.run` →
`FuncMetadata.validate_arguments` → `arg_model.model_validate`), и его отказ — текст
pydantic: имя присланного и `extra_forbidden` или `missing`. Агент по нему не узнаёт, что
инструмент принимает, и что присланное верхним уровнем лежит во вложенном аргументе
(`goal` у `create_task` — поле `sections`, `done` у `close_task` — поле `summary`).

Факты берутся из схемы аргументов самого инструмента — его модели аргументов, — а не
пишутся руками для трёх инструментов (TRK#219): новый инструмент получает их сам. Текст
отказа — факты, без предписаний: ошибка говорит, что не так и почему (TRK#182).

## Почему подмена `model_validate` на базе, а не слой сообщений

Отказ обязан остаться результатом с признаком ошибки, а не ошибкой протокола (шапка
`app/mcp/toolset.py`), поэтому дополнять его можно только внутри разбора. Базовая модель
аргументов SDK — единственное общее место всех инструментов; её `model_validate` зовёт
`validate_arguments`. Подменённый метод ловит `ValidationError` и собирает такой же, с
теми же строками и двумя добавленными: SDK печатает его целиком (`Tool.run`).
"""

import types
import typing
from typing import Any

from mcp.server.mcpserver.utilities.func_metadata import ArgModelBase
from pydantic import BaseModel, ValidationError
from pydantic_core import InitErrorDetails, PydanticCustomError

#: Тип строки, которой отказ перечисляет принимаемые аргументы.
ACCEPTED_ARGUMENTS = "accepted_arguments"

#: Тип строки о присланном верхним уровнем поле вложенного аргумента.
NESTED_ARGUMENT = "nested_argument_field"


def accepted_names(model: type[BaseModel]) -> list[str]:
    """Имена полей модели так, как их шлёт клиент: псевдоним, если он есть."""
    return [field.alias or name for name, field in model.model_fields.items()]


def nested_models(annotation: Any) -> list[type[BaseModel]]:
    """Модели, вложенные в аннотацию поля: через `X | None`, списки и объединения."""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return [annotation]
    found: list[type[BaseModel]] = []
    if typing.get_origin(annotation) in (typing.Union, types.UnionType, list, tuple, set):
        for part in typing.get_args(annotation):
            found.extend(nested_models(part))
    return found


def containers_of(model: type[BaseModel], name: str) -> list[str]:
    """Аргументы верхнего уровня, во вложенной модели которых есть поле `name`."""
    holders = []
    for field_name, field in model.model_fields.items():
        if any(name in accepted_names(inner) for inner in nested_models(field.annotation)):
            holders.append(field.alias or field_name)
    return holders


def enriched(model: type[BaseModel], error: ValidationError) -> ValidationError:
    """Тот же отказ плюс перечень принимаемых аргументов и место присланных не там.

    Не удалось собрать — вернуть прежний: дополнение не должно отнимать причину.
    """
    lines = error.errors(include_url=False, include_context=True, include_input=True)
    try:
        rebuilt: list[InitErrorDetails] = []
        for line in lines:
            detail = InitErrorDetails(type=line["type"], loc=line["loc"], input=line["input"])
            if "ctx" in line:
                detail["ctx"] = line["ctx"]
            rebuilt.append(detail)
        for line in lines:
            if line["type"] != "extra_forbidden" or len(line["loc"]) != 1:
                continue
            name = str(line["loc"][0])
            holders = containers_of(model, name)
            if holders:
                rebuilt.append(
                    InitErrorDetails(
                        type=PydanticCustomError(
                            NESTED_ARGUMENT,
                            "`{name}` is a field of the argument {holders}, not a top-level one",
                            {"name": name, "holders": ", ".join(f"`{h}`" for h in holders)},
                        ),
                        loc=line["loc"],
                        input=line["input"],
                    )
                )
        rebuilt.append(
            InitErrorDetails(
                type=PydanticCustomError(
                    ACCEPTED_ARGUMENTS,
                    "The tool accepts these arguments: {names}",
                    {"names": ", ".join(f"`{n}`" for n in accepted_names(model))},
                ),
                loc=(),
                input=None,
            )
        )
        return ValidationError.from_exception_data(error.title, rebuilt)
    except Exception:  # дополнение необязательно, исходный отказ важнее
        return error


def install() -> None:
    """Подменяет `model_validate` базовой модели аргументов: отказ приходит дополненным.

    Опора на устройство SDK, как и запрет лишнего в шапке `app/mcp/toolset.py`: SDK зовёт
    `arg_model.model_validate`, и подмена на базе действует на каждый инструмент, в том
    числе заведённый позже.
    """
    original = ArgModelBase.model_validate.__func__  # type: ignore[attr-defined]

    def model_validate(cls: type[BaseModel], obj: Any, **kwargs: Any) -> Any:
        try:
            return original(cls, obj, **kwargs)
        except ValidationError as error:
            raise enriched(cls, error) from None

    ArgModelBase.model_validate = classmethod(model_validate)  # type: ignore[method-assign,assignment]
