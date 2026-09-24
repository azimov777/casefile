# app/mcp/tools/registries

Инструменты по реестрам очередей и участников: файл на инструмент, чтение — набору `task`,
запись — `main`. Реестр группы — `TOOLS` в `__init__.py`: он же задаёт порядок в `tools/list`.

## Файлы
- `__init__.py` — реестр группы: модули инструментов по порядку `tools/list`
- `arguments.py` — описание участника, общее для регистрации и правки
- `views.py` — короткие ответы записи: ключ очереди, имя участника
- `get_queue.py` — `get_queue`: очередь с описанием
- `list_queues.py` — `list_queues`: очереди строкой, страницами
- `list_participants.py` — `list_participants`: реестр участников, страницами
- `create_queue.py` — `create_queue`: ключ, название и описание новой очереди
- `update_queue.py` — `update_queue`: новое название и описание, без следа прежних
- `register_participant.py` — `register_participant`: род и имя нового участника
- `update_participant.py` — `update_participant`: новое описание участника
