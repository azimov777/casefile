# e2e-demo

Не сквозные тесты — материал для `docs/assets/demo.gif` (TRK-82). Отдельно от
`ui/e2e/`, чтобы `pnpm e2e` его не подхватывал: свой `testDir`
(`../playwright.demo.config.ts`), свой контур бэкенда.

Плёнку не поднимает `globalSetup`, как `ui/e2e/` — контур здесь одноразовый,
с показательными данными, а не тот, что использует обычный прогон. Ниже —
команды, которыми контур поднят и наполнен для записи; повторяются вручную.

## 1. Поднять изолированный бэкенд

Свой проект Compose и свои порты — не трогать `docker-compose.yml` соседних
рабочих деревьев (`docs/notes/docker.md`, `parallel-agents-via-git-worktrees`).
Тег образа тоже свой: базовый `docker-compose.yml` пишет `image: tracker-dev:latest`
без параметра, и без надстройки сборка затёрла бы тег соседнего дерева. Надстройка
ниже переопределяет тег только для сервисов, которые здесь нужны:

```bash
cat > /tmp/demo-compose-override.yml <<'EOF'
services:
  api: { image: demo-dev:latest }
  mcp: { image: demo-dev:latest }
  migrate: { image: demo-dev:latest }
  init: { image: demo-dev:latest }
EOF

cd .. # корень репозитория
export COMPOSE_PROJECT_NAME=demo POSTGRES_PORT=5544 TRACKER_PORT=9020 TRACKER_MCP_PORT=9120
docker compose -f docker-compose.yml -f /tmp/demo-compose-override.yml up -d --build db api mcp
docker compose -f docker-compose.yml -f /tmp/demo-compose-override.yml run --rm migrate
docker compose -f docker-compose.yml -f /tmp/demo-compose-override.yml run --rm init
# печатает секрет владельца один раз — сохранить в файл, например .secrets/demo-owner-token
```

## 2. Завести агента `claude` и наполнить фон

```bash
OWNER=$(cat .secrets/demo-owner-token)
curl -s -X POST http://localhost:9020/api/v1/participants \
  -H "Authorization: Bearer $OWNER" -H "Content-Type: application/json" \
  -d '{"kind":"agent","name":"claude","description":"Agent working the Checkout service queue"}'

CLAUDE=$(curl -s -X POST http://localhost:9020/api/v1/tokens \
  -H "Authorization: Bearer $OWNER" -H "Content-Type: application/json" \
  -d '{"name":"demo-recording","scope":"task","participant":"claude"}' | python3 -c "import json,sys;print(json.load(sys.stdin)['data']['secret'])")
echo -n "$CLAUDE" > .secrets/demo-claude-token

DEMO_API_URL=http://localhost:9020 python3 ui/e2e-demo/seed-background.py \
  .secrets/demo-owner-token .secrets/demo-claude-token
```

Заводит очередь `APP` («Checkout service») и пять фоновых задач — по одной на
`backlog`/`open`/`in_progress`/`waiting`/`done` — так, чтобы доска уже выглядела
живой до начала записи. Идемпотентности нет: повторный запуск на той же базе
упадёт на создании очереди — начинать заново `docker compose down -v`.

## 3. Поднять интерфейс на том же бэкенде

Интерфейс из `ui/docker-compose.yml` поднимает **свой** бэкенд — здесь нужен не
он, а nginx, смотрящий на бэкенд из шага 1. Подключается к его сети напрямую:

```bash
cd ui
docker build -t demo-ui:latest -f docker/Dockerfile .
docker run -d --name demo-ui \
  --network demo_default \
  -p 127.0.0.1:9082:80 \
  -e TRACKER_API_URL=http://api:8000 \
  -e TRACKER_UI_TOKEN="$OWNER" \
  demo-ui:latest
```

## 4. Записать

```bash
DEMO_AGENT_TOKEN="$CLAUDE" DEMO_API_URL=http://localhost:9020 DEMO_UI_URL=http://localhost:9082 \
  npx playwright test -c playwright.demo.config.ts
```

Видео ложится в `test-results/**/video.webm` (гитигнорится, `../.gitignore`).
Сценарий — `demo-recording.spec.ts`: открывает доску, заводит задачу REST-вызовом
от лица `claude` (агент из шага 2), двигает её по статусам, подшивает записи,
открывает карточку. Каждый REST-вызов — то же самое, что сделал бы вызов
инструмента MCP: оба идут через один сценарий `services` (`docs/CONVENTIONS.md`).

## 5. Свести в GIF

`ffmpeg` на хосте нет — конвертация в контейнере (образ `jrottenberg/ffmpeg:7-alpine`
подтянулся без проблем). `-ss 0.5` срезает первый кадр записи (пустая страница до
навигации — иначе GIF мигал бы им на каждом повторе цикла):

```bash
docker run --rm -v "$PWD:/w" -w /w jrottenberg/ffmpeg:7-alpine \
  -ss 0.5 -i test-results/**/video.webm \
  -vf "fps=15,scale=1100:-1:flags=lanczos,split[s0][s1];[s0]palettegen=stats_mode=diff[p];[s1][p]paletteuse=dither=bayer:bayer_scale=3" \
  -loop 0 ../docs/assets/demo.gif
```

`fps=15`, ширина `1100` и палитра через `palettegen`/`paletteuse` (а не
единственная общая палитра) — компромисс, при котором ~18 секунд записи 1280×800
укладываются в 4–5 МБ (потолок — 10 МБ, `docs/CONVENTIONS.md`, задача TRK-82).

## 6. Погасить

```bash
docker rm -f demo-ui
cd .. && docker compose -f docker-compose.yml -f /tmp/demo-compose-override.yml -p demo down -v
```

## Файлы

- `README.md` — этот файл
- `demo-recording.spec.ts` — сценарий записи: доска, живое создание задачи агентом
  через REST, движение по статусам, записи дела, переход в карточку
- `seed-background.py` — наполняет фон (пять задач очереди `APP`) до начала записи,
  без внешних зависимостей (только `python3` из стандартной библиотеки)
