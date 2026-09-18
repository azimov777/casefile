# e2e-demo

Не сквозные тесты — материал для `docs/assets/demo-light.gif`/`demo-dark.gif`
(TRK-82). Отдельно от `ui/e2e/`, чтобы `pnpm e2e` его не подхватывал: свой
`testDir` (`../playwright.demo.config.ts`), свой контур бэкенда.

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

Заводит очередь `APP` («Checkout service») и девять фоновых задач — 3 в
`backlog`, 2 в `open`, 2 в `in_progress`, по одной в `waiting` и `done` — так,
чтобы самая длинная колонка доски уже стояла близко к высоте страницы задачи
(её кадр — самый высокий из всех сцен записи, см. следующий шаг), а не пустовала
под записью (TRK-82). Названия заголовков — короткие, в одну строку: у карточки
шире одной строки риск переполнить видимую высоту колонки раньше времени
(`fold:overflow-y-auto` в `tasks-board.tsx` включает свою прокрутку колонки, и
часть карточек ушла бы за пределы кадра). Идемпотентности нет: повторный запуск
на той же базе упадёт на создании очереди — начинать заново `docker compose down -v`.

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

README вставляет GIF парой (светлая/тёмная тема, `<picture>` — как раньше со
статичным скриншотом доски), поэтому сценарий гоняется дважды —
`DEMO_COLOR_SCHEME` переключает тему в `playwright.demo.config.ts`:

```bash
DEMO_AGENT_TOKEN="$CLAUDE" DEMO_API_URL=http://localhost:9020 DEMO_UI_URL=http://localhost:9082 \
  npx playwright test -c playwright.demo.config.ts
mv test-results/**/video.webm /tmp/demo-light.webm

DEMO_AGENT_TOKEN="$CLAUDE" DEMO_API_URL=http://localhost:9020 DEMO_UI_URL=http://localhost:9082 \
  DEMO_COLOR_SCHEME=dark npx playwright test -c playwright.demo.config.ts
mv test-results/**/video.webm /tmp/demo-dark.webm
```

(гитигнорится, `../.gitignore`.) Сценарий — `demo-recording.spec.ts`: открывает
доску, заводит задачу REST-вызовом от лица `claude` (агент из шага 2), двигает
её по статусам, подшивает записи, открывает карточку. Каждый REST-вызов — то же
самое, что сделал бы вызов инструмента MCP: оба идут через один сценарий
`services` (`docs/CONVENTIONS.md`). Разметка от темы не зависит — только цвета
токенов, — поэтому геометрия (и, значит, обрезка в следующем шаге) у обеих
записей одна и та же.

## 5. Свести в GIF

`ffmpeg` на хосте нет — конвертация в контейнере (образ `jrottenberg/ffmpeg:7-alpine`
подтянулся без проблем). `-ss 0.5` срезает первый кадр записи (пустая страница до
навигации — иначе GIF мигал бы им на каждом повторе цикла). `crop=1280:740:0:0`
идёт **до** `scale` и срезает пустой низ кадра: доска — `fold:h-(--ui-board-height)`
в `pages/tasks/ui/tasks-board.tsx` растягивает столбцы на весь `100dvh` за вычетом
шапки независимо от числа карточек в них, и при записи 1280×800 под этим всегда
остаётся полоса пустого фона. Высота обрезки взята не от доски (там своя высота, содержимое кончается заметно
раньше низа кадра), а от **самой высокой сцены записи** — дела на странице задачи
(`REVIEW CHECKS` внизу правой колонки кончаются примерно на 700px по вертикали);
обрезка по низу доски срезала бы там записи и подпись агента, ради которых
и снимали. Проверено покадрово после пересборки, что при этой высоте ничего
важного не обрезано ни на одной сцене. Прогнать на обоих файлах из шага 4
(пути ниже — под `/tmp`, куда легли `mv`):

```bash
for theme in light dark; do
docker run --rm -v "/tmp:/w" -w /w jrottenberg/ffmpeg:7-alpine \
  -ss 0.5 -i demo-$theme.webm \
  -vf "crop=1280:740:0:0,fps=15,scale=1100:-1:flags=lanczos,split[s0][s1];[s0]palettegen=stats_mode=diff[p];[s1][p]paletteuse=dither=bayer:bayer_scale=3" \
  -loop 0 demo-$theme.gif
done
cp /tmp/demo-light.gif /tmp/demo-dark.gif ../docs/assets/
```

`fps=15`, ширина `1100` и палитра через `palettegen`/`paletteuse` (а не
единственная общая палитра) — компромисс, при котором ~18–22 секунды записи
укладываются в 5–7 МБ каждая (потолок — 10 МБ, `docs/CONVENTIONS.md`, задача TRK-82).

## 6. Погасить

```bash
docker rm -f demo-ui
cd .. && docker compose -f docker-compose.yml -f /tmp/demo-compose-override.yml -p demo down -v
```

## Файлы

- `README.md` — этот файл
- `demo-recording.spec.ts` — сценарий записи: доска, живое создание задачи агентом
  через REST, движение по статусам, записи дела, переход в карточку
- `seed-background.py` — наполняет фон (девять задач очереди `APP`) до начала записи,
  без внешних зависимостей (только `python3` из стандартной библиотеки)
