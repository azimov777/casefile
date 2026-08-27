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
curl http://localhost:8000/health
```

Ответ здорового сервиса:

```json
{"status": "ok", "version": "0.1.0", "environment": "local", "database": "ok"}
```

Документация API — http://localhost:8000/docs, схема — http://localhost:8000/openapi.json.

## Команды разработки

| Что нужно | Команда |
|---|---|
| Поднять контур | `docker compose up -d` |
| Логи сервера | `docker compose logs -f api` |
| Применить миграции | `docker compose run --rm migrate` |
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
  db/           модели SQLAlchemy, сессии, миграции
  automation/   движок автоматики
  core/         конфиг, логирование, базовые исключения
docker/         образы для разработки и продакшена
docs/           концепция, соглашения, задания
tests/          тесты и общие фикстуры
```

В каждой папке лежит `AGENTS.md` с картой её содержимого.
