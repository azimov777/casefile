"""Скил Casefile по SEP-2640: расширение `io.modelcontextprotocol/skills`.

Единственный источник скила — `skills/casefile/SKILL.md` в корне репозитория; тот же
каталог указывает манифест плагина маркетплейса, копий нет (`TRK-399#13`). Сервер отдаёт
его двумя путями: методами `skills/list` и `skills/get` клиентам с поддержкой SEP-2640 и
обычными ресурсами `skill://casefile/<путь>` (`resources/list`, `resources/read`) любому
клиенту MCP.

Расширение собрано на публичном механизме SDK (`Extension`, `MethodBinding`), а не на
`Skills` из python-sdk#3485: тот запрос не слит, и его API может переехать. Переход на
SDK после выпуска — `TRK-407`.

Каталог читается при импорте сборки: без файла процесс не поднимется, а не отдаст пустой
список скилов — как и `instructions.md`.
"""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from mcp.server.context import ServerRequestContext
from mcp.server.extension import Extension, MethodBinding, ResourceBinding
from mcp.server.mcpserver.resources import TextResource
from mcp.shared.exceptions import MCPError
from mcp_types import INVALID_PARAMS, PaginatedRequestParams, RequestParams
from mcp_types.version import MODERN_PROTOCOL_VERSIONS

__all__ = [
    "MAX_SKILL_BYTES",
    "MAX_SKILL_FILES",
    "SKILLS_DIR",
    "SKILLS_EXTENSION",
    "CasefileSkills",
    "GetSkillParams",
    "advertise_on_handshake",
]

#: Корень скилов: `skills/` в корне репозитория и в образе (`/app/skills`).
SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills"

#: Идентификатор расширения в `capabilities.extensions`.
SKILLS_EXTENSION = "io.modelcontextprotocol/skills"

#: Срок, на который клиент может запомнить ответ, миллисекунды. Только на эпохе
#: 2026-07-28: на старой этих полей в результате нет.
_TTL_MS = 300_000

#: Лимиты одного скила из SEP-2640 (Final, «Limits»): записей в `resources` и сумма `size`.
#: Сервер не должен отдавать скил больше, поэтому такой каталог не поднимается.
MAX_SKILL_FILES = 512
MAX_SKILL_BYTES = 16 * 1024 * 1024


class GetSkillParams(RequestParams):
    """Параметры `skills/get`: адрес `SKILL.md` нужного скила."""

    uri: str


@dataclass(frozen=True)
class _File:
    uri: str
    path: Path
    digest: str
    size: int


@dataclass(frozen=True)
class _Skill:
    uri: str
    frontmatter: dict[str, Any]
    files: tuple[_File, ...]

    def entry(self) -> dict[str, Any]:
        return {
            "uri": self.uri,
            "frontmatter": self.frontmatter,
            "resources": [
                {"uri": item.uri, "digest": item.digest, "size": item.size} for item in self.files
            ],
        }


def _frontmatter(text: str, source: Path) -> dict[str, Any]:
    parts = text.split("---", 2)
    if len(parts) < 3 or parts[0].strip():
        raise ValueError(f"{source}: no YAML frontmatter")
    data = yaml.safe_load(parts[1])
    if not isinstance(data, dict) or "name" not in data or "description" not in data:
        raise ValueError(f"{source}: frontmatter needs `name` and `description`")
    return data


def _load(root: Path) -> dict[str, _Skill]:
    skills: dict[str, _Skill] = {}
    for directory in sorted(item for item in root.iterdir() if item.is_dir()):
        manifest = directory / "SKILL.md"
        front = _frontmatter(manifest.read_text(encoding="utf-8"), manifest)
        if front["name"] != directory.name:
            raise ValueError(f"{manifest}: name {front['name']!r} differs from the directory")
        files = []
        for path in sorted(item for item in directory.rglob("*") if item.is_file()):
            raw = path.read_bytes()
            files.append(
                _File(
                    uri=f"skill://{directory.name}/{path.relative_to(directory).as_posix()}",
                    path=path,
                    digest="sha256:" + hashlib.sha256(raw).hexdigest(),
                    size=len(raw),
                )
            )
        total = sum(item.size for item in files)
        if len(files) > MAX_SKILL_FILES or total > MAX_SKILL_BYTES:
            raise ValueError(
                f"{directory}: {len(files)} files, {total} bytes exceed the SEP-2640 limits "
                f"({MAX_SKILL_FILES} files, {MAX_SKILL_BYTES} bytes)"
            )
        skill = _Skill(
            uri=f"skill://{directory.name}/SKILL.md", frontmatter=front, files=tuple(files)
        )
        skills[skill.uri] = skill
    if not skills:
        raise ValueError(f"{root}: no skills found")
    return skills


class CasefileSkills(Extension):
    """Расширение SEP-2640 без `directoryRead`: перечень, выдача и ресурсы файлов."""

    identifier = SKILLS_EXTENSION

    def __init__(self, root: Path = SKILLS_DIR) -> None:
        self._skills = _load(root)

    def resources(self) -> Sequence[ResourceBinding]:
        bindings = []
        for skill in self._skills.values():
            for item in skill.files:
                is_manifest = item.uri == skill.uri
                name = skill.frontmatter["name"] if is_manifest else item.uri.split("/", 3)[3]
                bindings.append(
                    ResourceBinding(
                        TextResource(
                            uri=item.uri,
                            name=name,
                            description=skill.frontmatter["description"] if is_manifest else None,
                            mime_type="text/markdown",
                            text=item.path.read_text(encoding="utf-8"),
                        )
                    )
                )
        return bindings

    def methods(self) -> Sequence[MethodBinding]:
        async def list_skills(
            ctx: ServerRequestContext[Any, Any], params: PaginatedRequestParams
        ) -> dict[str, Any]:
            del params
            return _cacheable(ctx, {"skills": [skill.entry() for skill in self._skills.values()]})

        async def get_skill(
            ctx: ServerRequestContext[Any, Any], params: GetSkillParams
        ) -> dict[str, Any]:
            skill = self._skills.get(params.uri)
            if skill is None:
                raise MCPError(code=INVALID_PARAMS, message=f"No skill is served at {params.uri}")
            return _cacheable(ctx, {"skill": skill.entry()})

        return (
            MethodBinding("skills/list", PaginatedRequestParams, list_skills),
            MethodBinding("skills/get", GetSkillParams, get_skill),
        )


def _cacheable(ctx: ServerRequestContext[Any, Any], result: dict[str, Any]) -> dict[str, Any]:
    """Срок хранения ответа — только на эпохе 2026-07-28, где эти поля есть."""
    if ctx.protocol_version in MODERN_PROTOCOL_VERSIONS:
        result |= {"ttlMs": _TTL_MS, "cacheScope": "public"}
    return result


async def advertise_on_handshake(ctx: ServerRequestContext[Any, Any], call_next: Any) -> Any:
    """Дописывает расширение в ответ `initialize` эпохи 2025-11-25.

    SDK кладёт `capabilities.extensions` только в ответ `server/discover` эпохи
    2026-07-28, а в рукопожатии старой эпохи срезает поле по схеме той версии. Клиенты
    же пока ходят именно рукопожатием, и без объявления не ищут скилов вовсе
    (`TRK/mcp#39`).
    """
    result = await call_next(ctx)
    if ctx.method == "initialize" and isinstance(result, dict):
        result.setdefault("capabilities", {}).setdefault("extensions", {})[SKILLS_EXTENSION] = {}
    return result
