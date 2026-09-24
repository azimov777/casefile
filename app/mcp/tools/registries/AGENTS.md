# app/mcp/tools/registries

Инструменты по реестрам проектов и участников: файл на инструмент, чтение — набору `task`,
запись — `main`, кроме атрибутов проекта: их задаёт и снимает набор `task`. Реестр группы — `TOOLS` в `__init__.py`: он же задаёт порядок в `tools/list`.

## Файлы
- `__init__.py` — реестр группы: модули инструментов по порядку `tools/list`
- `arguments.py` — описание участника, общее для регистрации и правки; имя атрибута, общее для задания и снятия
- `views.py` — короткие ответы записи: ключ проекта, имя участника
- `get_project.py` — `get_project`: проект с описанием, атрибутами и описью его дела
- `list_projects.py` — `list_projects`: проекты строкой, страницами
- `list_participants.py` — `list_participants`: реестр участников, страницами
- `create_project.py` — `create_project`: ключ, название и описание нового проекта
- `update_project.py` — `update_project`: новое название и описание, прежние — в `field_changed` дела проекта
- `archive_project.py` — `archive_project`: заморозить проект и его задачи с причиной, запись `archived`
- `restore_project.py` — `restore_project`: вернуть проект из архива с причиной, запись `restored`
- `set_attribute.py` — `set_attribute`: завести атрибут проекта или изменить значение; тип записи выбирает трекер
- `remove_attribute.py` — `remove_attribute`: снять атрибут с причиной, последнее значение — в `attribute_removed`
- `register_participant.py` — `register_participant`: род и имя нового участника
- `update_participant.py` — `update_participant`: новое описание участника
