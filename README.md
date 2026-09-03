# Tracker

> **Переписывание под трекер для агентов.** Старый доменный слой снесён (задача 20),
> фундамент нового построен (задача 21). Задачи, дело, связи, поиск и лента строятся
> задачами 22–29 по `docs/CONCEPT.md`, порядок работ — в `docs/ROADMAP.md`, полная
> переработка этого файла — задача 29. Прежняя версия целиком доступна в git по
> коммиту `49e2e49`.
>
> Что сейчас работает: `/health`, участники, токены с наборами `task` / `main`, очереди
> со счётчиком номеров, аутентификация с меткой временного агента, задачи с пятью
> разделами, зашитыми статусами и переходами, служебные записи дела, оболочка ответа
> и коды ошибок, выгрузка OpenAPI, оба контура Docker. MCP-сервер поднимается и
> отвечает на `initialize`, но инструментов пока не объявляет — их строит задача 28.

Бэкенд трекера для агентов: REST API для фронтенда и MCP-сервер для агентов.
Что и зачем строим — `docs/CONCEPT.md`, правила разработки — `docs/CONVENTIONS.md`.

## Требования

Docker и Docker Compose. Больше ничего: Python, зависимости, миграции, тесты и линтер
живут в контейнерах. Установка Python на хост-машину не поддерживается и не нужна.

## Быстрый старт

```bash
cp .env.example .env          # необязательно: у дев-контура есть значения по умолчанию
docker compose up -d          # поднимает PostgreSQL и сервер
docker compose run --rm migrate   # применяет миграции
docker compose run --rm init      # заводит владельца и печатает его первый токен
curl http://localhost:8000/health
```

Ответ здорового сервиса:

```json
{"status": "ok", "version": "0.1.0", "environment": "local", "database": "ok"}
```

Документация API — http://localhost:8000/docs, схема — http://localhost:8000/openapi.json.

Коды ошибок с описанием, когда какой возникает, — в `docs/ERRORS.md`. Разработчику
интерфейса — `docs/FRONTEND.md`; он описывает прежний API и будет переписан вместе с
новым доменом.

## Поставляемые артефакты контракта

```bash
docker compose run --rm schema
```

Пишет два файла: `openapi.json` — схему для генерации типизированного клиента, и
`docs/ERRORS.md` — справочник кодов ошибок. Базы команде не нужно: и то и другое —
свойства кода, а не работающей установки.

Схема пригодна к генерации клиента, и это проверяется тестом, а не обещается: у каждого
маршрута есть модель ответа, `operation_id` читаем и стабилен, перечисления — строковые
enum, объектов неизвестной формы нет нигде, кроме задокументированных мест.

```bash
npx openapi-typescript openapi.json -o src/shared/api/openapi.ts
```

`openapi.json` намеренно не хранится в репозитории — он всегда равен коду, и вторая копия
отставала бы от первой. `docs/ERRORS.md`, наоборот, коммитится: его читают в репозитории,
а расхождение с кодом ловит `tests/test_api_contract.py`.

В прод-контуре запись в `/app` недоступна (образ работает от непривилегированного
пользователя), поэтому схема идёт в стандартный вывод:

```bash
docker compose -f docker-compose.prod.yml run --rm --no-deps schema > openapi.json
```

## Доступ к API

Все маршруты `/api/v1` требуют токена — исключений нет. Вне защиты остался только `/health`:
он для Docker и мониторинга и в контракт с фронтендом не входит.

```bash
curl -H "Authorization: Bearer trk_..." http://localhost:8000/api/v1/participants
```

### Первичная инициализация

Первый токен взять неоткуда, кроме командной строки: выпустить его через API нельзя, потому
что API уже требует токен. Это и делает `docker compose run --rm init` — заводит
участника-человека `owner` и печатает его токен набора `main`.

Команда срабатывает **только на пустой установке**: если в базе есть хотя бы один токен, она
ничего не создаёт и говорит об этом. Так её можно держать рядом с миграциями, не боясь, что
случайный повторный запуск наплодит действующие доступы. Потеряли секрет — выпускайте новый
явно:

```bash
docker compose run --rm --entrypoint python api -m app.cli issue-token \
       --participant owner --scope main
```

Токен показывается **один раз**: в базе лежит только его хеш, восстановить секрет нельзя.

### Наборы токена

Прав в трекере ровно одно — набор токена. Ролей, владельцев и разрешений по роду участника
нет: любую запись и любой переход может сделать кто угодно.

| Набор | Что открывает |
|---|---|
| `task` | Рабочий цикл агента: задачи, дело, связи, поиск, лента, чтение реестров. |
| `main` | То же плюс запись участников, токенов и очередей. |

### Участники, токены и очереди

```bash
# завести постоянного агента (нужен набор main)
curl -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
     -d '{"kind": "agent", "name": "release_bot", "description": "Релизный бот"}' \
     http://localhost:8000/api/v1/participants

# выпустить ему токен рабочего цикла (секрет виден только в этом ответе)
curl -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
     -d '{"name": "ci", "scope": "task", "participant": "release_bot"}' \
     http://localhost:8000/api/v1/tokens

# завести очередь
curl -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
     -d '{"key": "TRK", "title": "Трекер", "description": "Где лежит код, куда смотреть"}' \
     http://localhost:8000/api/v1/queues

# отозвать токен
curl -X DELETE -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/tokens/$TOKEN_ID
```

Имена участников уникальны без учёта регистра и хранятся в нижнем; ключи очередей — в
верхнем. Переименования нет ни у тех, ни у других: имя стоит подписью в записях дела, ключ
вшит в ключ каждой задачи очереди. Удаления тоже нет — доступ снимается отзывом токена.

### Задачи и дело

Задача рождается в `backlog` и живёт по зашитой таблице переходов: `backlog → open →
in_progress → review → done`, из любого незакрытого статуса — в `cancelled`. Шаг назад и
отмена требуют `reason`; перед `open` четыре раздела и `checks` должны быть заполнены.
Название, описание и разделы правятся только в `backlog`; исполнитель, теги и приоритет
— в любом незакрытом статусе. Каждое действие подшивает служебную запись в дело.

```bash
# завести задачу (набора task достаточно)
curl -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
     -d '{"queue": "TRK", "title": "Починить выдачу ключей", "description": "Ключ сгорает",
          "goal": "...", "context": "...", "constraints": "...", "output": "...",
          "checks": ["Пустое название не тратит номер"]}' \
     http://localhost:8000/api/v1/tasks

# пакет преемника: карточка, признаки, последняя сводка, открытые вопросы, опись дела
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/tasks/TRK-1

# поправить раздел (только в backlog) с проверкой версии
curl -X PATCH -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
     -d '{"goal": "Ключи не сгорают", "version": 1}' http://localhost:8000/api/v1/tasks/TRK-1

# перевести статус; шаг назад — с причиной
curl -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
     -d '{"to": "open"}' http://localhost:8000/api/v1/tasks/TRK-1/transition

# записи дела с телами и нагрузкой; фильтры nos, types, after_no
curl -H "Authorization: Bearer $TOKEN" \
     'http://localhost:8000/api/v1/tasks/TRK-1/entries?types=summary&after_no=3'

# одна запись по её номеру в задаче — адрес из ссылки TRK-1#5
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/tasks/TRK-1/entries/5
```

#### Записи агента

Дело пополняется одним маршрутом `POST /tasks/{key}/entries`. Тело — размеченное по
`type` объединение: у каждого типа своя форма `payload`, и клиент, сгенерированный из
OpenAPI, знает её точно.

```bash
# сводка: четыре части, все непустые. Заголовок не принимается — им становится
# первая строка next_step
curl -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
     -d '{"type": "summary", "payload": {"done": "Разобрался", "remaining": "Дописать",
          "blockers": "нет", "next_step": "Перенести вызов в конец create_task"}}' \
     http://localhost:8000/api/v1/tasks/TRK-1/entries

# вопрос участнику реестра; blocking обязателен и значения по умолчанию не имеет
curl -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
     -d '{"type": "question", "title": "Какой ключ канонический?",
          "payload": {"addressees": ["owner"], "blocking": true}}' \
     http://localhost:8000/api/v1/tasks/TRK-1/entries

# вердикт по обзорной проверке; тело записи — доказательство
curl -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
     -d '{"type": "verdict", "body": "Прогон зелёный",
          "payload": {"check_no": 1, "outcome": "passed"}}' \
     http://localhost:8000/api/v1/tasks/TRK-1/entries

# решение, попытка, находка, артефакт, заметка — без нагрузки, но с заголовком
curl -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
     -d '{"type": "finding", "title": "Номер выдаётся до валидации",
          "refs": ["TRK-1#3", "https://example.com/pr/12"]}' \
     http://localhost:8000/api/v1/tasks/TRK-1/entries
```

Заголовок принимается только там, где его нечем вывести. У `summary` он равен первой
строке `next_step`, у `answer` и `verdict` собирается из нагрузки. Служебные типы
(`status_changed`, `created`, ...) подшивает сам трекер, и в запросе они не принимаются.
`refs` со ссылками на задачи (`TRK-7`) и записи (`TRK-42#12`) проверяются на
существование; адреса — нет.

Две валидации перехода живут именно здесь: выход из `in_progress` требует сводки,
подшитой **после последнего входа** в него (`409 summary_required`), а `review → done` —
чтобы последний по времени вердикт каждой проверки был `passed` (`409 checks_not_passed`,
проверки без него — в `details.checks`).

Записи дела неизменяемы: маршрутов правки и удаления нет, а триггер в базе отклоняет
`UPDATE` и `DELETE`. Ошибочная запись исправляется следующей. В закрытую задачу записи
подшивать можно — меняться нельзя полям, а не делу.

#### Вопросы

Вопрос — не отдельная сущность, а представление над делом: он открыт, пока в той же
задаче нет записи `answer` с его номером.

```bash
# входящая: по умолчанию открытые вопросы участника, чьим токеном сделан запрос
curl -H "Authorization: Bearer $TOKEN" \
     'http://localhost:8000/api/v1/questions?blocking=true&queue=TRK'

# ответить — записью в дело той задачи, где вопрос задан
curl -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
     -d '{"type": "answer", "body": "Верхний регистр", "payload": {"question_no": 4}}' \
     http://localhost:8000/api/v1/tasks/TRK-1/entries
```

### Временные агенты и `X-Actor-Label`

Токен, выпущенный **без** `participant`, — общий агентский. Он не называет автора сам, и
каждый запрос с ним обязан нести метку временного агента:

```bash
curl -X POST -H "Authorization: Bearer $SHARED_TOKEN" -H "X-Actor-Label: nightly_agent" \
     -H 'Content-Type: application/json' -d '{"key": "OPS", "title": "Эксплуатация"}' \
     http://localhost:8000/api/v1/queues
```

Без заголовка запрос отклоняется с кодом `actor_label_required`: приписать действие некому.
Именной токен метку игнорирует — его подпись всегда имя своего участника, и подделать её
заголовком нельзя. Временного агента нельзя адресовать вопросом: для этого участника надо
завести в реестре.

## MCP-сервер для агентов

Второй интерфейс трекера. Агент (Claude Code и подобные) ходит не в REST, а в MCP: те же
сценарии, но инструментами, описания которых читает модель.

**Инструментов сейчас нет.** Старый набор снесён вместе со старым доменом, новый строится
задачей 28. До неё сервер поднимается, отвечает на `initialize` и отдаёт пустой
`tools/list` — подключиться к нему можно, сделать им пока нечего.

```bash
docker compose up -d mcp          # поднимается вместе с контуром
curl http://localhost:8100/health
```

```json
{"status": "ok", "version": "0.1.0", "database": "ok"}
```

Адрес — `http://localhost:8100/mcp`, транспорт — streamable HTTP, авторизация — тем же
токеном, что и REST: `Authorization: Bearer trk_...` плюс `X-Actor-Label`, если токен общий
агентский. Второй схемы представления нет намеренно — участники и токены общие на оба
интерфейса.

### Подключение к Claude Code

Сервер работает в контейнере, наружу опубликован порт `8100` (`TRACKER_MCP_PORT`).
Токен агенту выпускают через REST — MCP этого не умеет и не будет уметь: выдача доступов
остаётся за человеком.

```bash
# завести агента и выпустить ему токен (секрет виден только в этом ответе)
curl -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
     -d '{"kind": "agent", "name": "claude", "description": "Claude Code"}' \
     http://localhost:8000/api/v1/participants
curl -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
     -d '{"name": "claude-code", "scope": "task", "participant": "claude"}' \
     http://localhost:8000/api/v1/tokens

# подключить сервер (scope local — конфигурация только этого проекта, без репозитория)
claude mcp add --scope local --transport http tracker http://localhost:8100/mcp \
      --header "Authorization: Bearer trk_..."

claude mcp list    # tracker: http://localhost:8100/mcp (HTTP) - ✔ Connected
```

Если Claude Code работает не на той машине, где поднят контур, вместо `localhost` идёт
адрес хоста, а порт `8100` должен быть до него доступен. Токен кладите в конфигурацию
клиента, а не в репозиторий: `--scope local` пишет его в личный файл настроек.

## Команды разработки

| Что нужно | Команда |
|---|---|
| Поднять контур | `docker compose up -d` |
| Логи сервера | `docker compose logs -f api` |
| Логи MCP-сервера | `docker compose logs -f mcp` |
| Перезапустить MCP-сервер после правки | `docker compose restart mcp` |
| Применить миграции | `docker compose run --rm migrate` |
| Инициализировать пустую установку | `docker compose run --rm init` |
| Выпустить токен | `docker compose run --rm --entrypoint python api -m app.cli issue-token --participant release_bot --scope task` |
| Выгрузить схему и справочник ошибок | `docker compose run --rm schema` |
| Создать миграцию | `docker compose run --rm migrate alembic revision --autogenerate -m "описание"` |
| Откатить миграцию | `docker compose run --rm migrate alembic downgrade -1` |
| Прогнать тесты | `docker compose run --rm test` |
| Один тест | `docker compose run --rm test pytest tests/test_health.py -k health` |
| Линтер и форматтер | `docker compose run --rm lint` |
| Отформатировать код | `docker compose run --rm --entrypoint ruff lint format .` |
| Консоль в контейнере | `docker compose run --rm --entrypoint bash api` |
| Остановить | `docker compose down` (с данными: `docker compose down -v`) |

Правка исходника подхватывается автоматически: код смонтирован в контейнер, uvicorn
перезапускается сам. Пересборка образа нужна только после изменения `pyproject.toml`:

```bash
docker compose build api
```

### Миграции

Миграции применяются отдельной командой, а не при старте приложения: несколько реплик,
одновременно накатывающих схему, — это гонка и испорченная база. После правки моделей:

```bash
docker compose run --rm migrate alembic revision --autogenerate -m "что изменилось"
docker compose run --rm migrate
```

Автогенерация видит только те модели, которые импортированы в `app/db/models/__init__.py`.

Цепочка ревизий начата заново задачей 20: первая ревизия завела акторы и токены, вторая
(задача 21) заменила их участниками, токенами с наборами и очередями, третья (задача 22)
добавила задачи и записи дела. Прежняя схема живёт в git по коммиту `49e2e49`.

`alembic check` на сошедшейся схеме штатно сообщает о снятии `CHECK` у каждой колонки-
перечисления — это ложное срабатывание, объяснённое в `docs/notes/db.md`. Если в выводе
**только** такие строки, модели и схема совпадают.

### Тесты

`docker compose run --rm test` поднимает БД, создаёт базу `tracker_test`, накатывает на неё
миграции и прогоняет весь набор. Каждый тест идёт внутри транзакции, которая откатывается
после него, поэтому порядок тестов не влияет на результат.

## Продакшен-контур

```bash
cp .env.example .env          # обязательно: значения по умолчанию прод не подставляет
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml run --rm migrate
```

Отличия от контура разработки:

| | Разработка | Продакшен |
|---|---|---|
| Dockerfile | `docker/Dockerfile.dev` | `docker/Dockerfile.prod`, многостадийный |
| Код | смонтирован томом | скопирован в образ |
| Перезапуск при правке | есть (`--reload`) | нет |
| Зависимости | рантайм + dev | только рантайм |
| Пользователь | root | непривилегированный `tracker` |
| Порт БД наружу | опубликован | нет |
| Переменные окружения | есть значения по умолчанию | обязательны, иначе запуск падает |

Прод-образ примерно вдвое легче дев-образа: компиляторы остаются в стадии сборки.

## Конфигурация

Приложение настраивается только переменными окружения — один образ работает в любом
контуре без пересборки. Полный список с комментариями — в `.env.example`, разбор и
валидация — в `app/core/config.py`. Все переменные приложения начинаются с `TRACKER_`.

## Структура

```
app/
  api/          HTTP-слой: роутеры, схемы, обработка ошибок, контракт
  mcp/          MCP-сервер для агентов: пока каркас без инструментов (`python -m app.mcp`)
  domain/       доменные модели и правила
  services/     сценарии: транзакции, служебные записи
  db/           модели SQLAlchemy, репозитории, сессии, миграции
  core/         конфиг, логирование, базовые исключения
  cli.py        командная строка: настройка установки, выгрузка схемы и справочника
docker/         образы для разработки и продакшена
docs/           концепция, соглашения, задания, заметки
skill/          скил дисциплины работы с трекером, раздаётся агентам через MCP
tests/          тесты и общие фикстуры
```

Фоновых процессов нет: автоматики в трекере нет, а лента читается прямо из таблицы
записей — поэтому в обоих контурах Compose ровно четыре сервиса, БД, HTTP-сервер,
MCP-сервер и шаг миграций.

В каждой папке лежит `AGENTS.md` с картой её содержимого.
