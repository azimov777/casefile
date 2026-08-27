# Tracker

Бэкенд таск-трекера: REST API для фронтенда и MCP-сервер для агентов.
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

## Доступ к API

Все маршруты `/api/v1` требуют токена — исключений нет. Вне защиты остался только `/health`:
он для Docker и мониторинга и в контракт с фронтендом не входит.

```bash
curl -H "Authorization: Bearer trk_..." http://localhost:8000/api/v1/actors/me
```

Первый токен взять неоткуда, кроме командной строки: выпустить его через API нельзя, потому
что API уже требует токен. Это и делает `docker compose run --rm init` — заводит
актора-владельца и печатает его секрет. Команда идемпотентна: повторный запуск второго
владельца не создаёт, но выпускает новый токен, и это же способ вернуть себе доступ.

Токен показывается **один раз**: в базе лежит только его хеш, восстановить секрет нельзя.

Дальше акторы и токены заводятся через API — одним и тем же механизмом для людей и агентов:

```bash
# завести агента
curl -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
     -d '{"type": "agent", "key": "release_bot", "display_name": "Релизный бот"}' \
     http://localhost:8000/api/v1/actors

# выпустить ему токен (секрет виден только в этом ответе)
curl -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
     -d '{"name": "ci"}' \
     http://localhost:8000/api/v1/actors/release_bot/tokens

# отозвать токен
curl -X DELETE -H "Authorization: Bearer $TOKEN" \
     http://localhost:8000/api/v1/actors/release_bot/tokens/$TOKEN_ID
```

Системный актор (`system`) создаётся миграцией, от его имени работают автоматика и фоновые
процессы. Через API он защищён: его нельзя изменить и нельзя выпустить ему токен.

## Очереди и справочники

Очередь — контейнер конфигурации процесса: свой набор типов задач, свои значения по умолчанию,
свои локальные статусы и резолюции. Ключ очереди (`TRK`) неизменяем — на нём построены ключи
задач (`TRK-123`).

```bash
# создать очередь: без указаний она комплектуется глобальными справочниками и готова к работе
curl -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
     -d '{"key": "TRK", "name": "Трекер"}' \
     http://localhost:8000/api/v1/queues

# конфигурация целиком: типы, статусы, резолюции и поля одним запросом
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/queues/TRK/config

# архивация вместо удаления: очередь с задачами удалить нельзя
curl -X POST -H "Authorization: Bearer $TOKEN" \
     http://localhost:8000/api/v1/queues/TRK/archive
```

Статусы, типы задач и резолюции — редактируемые данные, а не зашитый список. Начальный набор
(`open`/`in_progress`/`closed`, `task`/`bug`/`epic`, `done`/`rejected`/`duplicate`) создаётся
миграцией такими же обычными записями: их можно переименовать, отключить и дополнить своими.

Запись справочника либо **глобальная** (доступна всем очередям, адресуется голым ключом `open`),
либо **локальная** для очереди (адресуется с префиксом: `TRK.in_review`).

```bash
# свой статус только для этой очереди
curl -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
     -d '{"key": "in_review", "name": "Ревью", "category": "in_progress", "queue": "TRK"}' \
     http://localhost:8000/api/v1/statuses

# чем можно пользоваться в очереди: глобальные записи плюс её собственные
curl -H "Authorization: Bearer $TOKEN" \
     'http://localhost:8000/api/v1/statuses?queue=TRK'
```

У каждого статуса обязательно есть **категория** — `new`, `in_progress` или `done`. На неё
опираются доски, прогресс проектов и автоматика, поэтому статус можно переименовать, ничего не
сломав. Сменить категорию у статуса, в котором стоят задачи, нельзя: это задним числом
переопределило бы, какие задачи считаются закрытыми.

Статус, которым пользуются, не удаляется — запрос отклоняется с кодом `status_in_use`. Порядок
такой: сначала перенести задачи, потом удалить. Ненужный, но исторически важный статус
правильнее не удалять, а отключить (`PATCH` с `is_active: false`) — история изменений останется
читаемой.

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
     -d '{"target_status": "open", "queue": "TRK"}' \
     http://localhost:8000/api/v1/statuses/TRK.in_review/move-issues
```

Ключи адресуются без учёта регистра (`trk.in_review` найдёт ту же запись), а вот придумать
кривой ключ при создании нельзя: ключи очередей — латиница в верхнем регистре, ключи
справочников — snake_case в нижнем.


## Кастомные поля

Разным процессам нужны разные атрибуты: у бага — серьёзность, у релиза — версия сборки. Поля
описываются в реестре и хранятся в `values JSONB` задачи, поэтому **новое поле не требует
миграции**. Область действия как у справочников: глобальное поле адресуется голым ключом
(`business_value`), локальное — с префиксом очереди (`TRK.severity`).

```bash
# перечисление, только для багов этой очереди, со значением по умолчанию
curl -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
     -d '{"key": "severity", "name": "Серьёзность", "value_type": "enum", "queue": "TRK",
          "issue_types": ["bug"], "is_required": true, "default_value": "minor",
          "options": [{"key": "minor", "name": "Мелкая"},
                      {"key": "critical", "name": "Критическая"}]}' \
     http://localhost:8000/api/v1/fields

# какие поля есть у задачи такого типа в этой очереди
curl -H "Authorization: Bearer $TOKEN" \
     'http://localhost:8000/api/v1/fields?queue=TRK&issue_type=bug'
```

Типы значений: `string`, `text`, `number`, `date`, `datetime`, `boolean`, `enum`, `actor`
(ссылка на актора), `issue` (ссылка на задачу). Любое поле может быть множественным
(`is_multiple`) — тогда оно хранит массив значений того же типа.

Формат записи в JSONB зафиксирован в докстринге `app/domain/fields.py` и обязателен для всех:
его читают история изменений, поиск и автоматика. Ключ в `values` — это **ссылка** на поле, а
не его ключ, иначе глобальное `severity` и локальное `TRK.severity` затирали бы друг друга.

Что нельзя менять: ключ поля (под ним лежат значения в задачах) и — у поля, в котором уже есть
данные, — тип и множественность. Переименование, обязательность и порядок показа меняются
всегда. Удалить поле со значениями нельзя: его **скрывают** (`PATCH` с `is_hidden: true`) —
поле исчезает из конфигурации очереди, но данные и история остаются читаемыми.

Валидатор значений возвращает **все** замечания сразу, а не первое: фронт подсвечивает всю
форму за один ответ, агент исправляет запрос за одну попытку.

```json
{"error": {"code": "field_values_invalid",
           "message": "Custom field values failed validation",
           "details": {"fields": [{"field": "TRK.severity", "reason": "required",
                                   "allowed": ["minor", "critical"]},
                                  {"field": "TRK.due_on", "reason": "invalid_date",
                                   "expected": "YYYY-MM-DD"}]}}}
```


## Команды разработки

| Что нужно | Команда |
|---|---|
| Поднять контур | `docker compose up -d` |
| Логи сервера | `docker compose logs -f api` |
| Применить миграции | `docker compose run --rm migrate` |
| Завести владельца и первый токен | `docker compose run --rm init` |
| Выпустить токен актору | `docker compose run --rm --entrypoint python api -m app.cli issue-token --actor release_bot` |
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
  api/          HTTP-слой: роутеры, схемы, обработка ошибок
  mcp/          MCP-сервер для агентов
  domain/       доменные модели и правила
  services/     сценарии: транзакции, события
  db/           модели SQLAlchemy, репозитории, сессии, миграции
  automation/   движок автоматики
  core/         конфиг, логирование, базовые исключения
  cli.py        командная строка: первичная настройка установки
docker/         образы для разработки и продакшена
docs/           концепция, соглашения, задания
tests/          тесты и общие фикстуры
```

В каждой папке лежит `AGENTS.md` с картой её содержимого.
