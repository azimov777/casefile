# Сборка статики и отдача её через nginx. Двухступенчатый образ: Node нужен только
# сборщику, в готовый образ он не попадает.
FROM node:22-alpine AS build

# Версия pnpm берётся из `packageManager` в package.json — corepack не даст разъехаться
# со сборкой на машине разработчика.
RUN corepack enable

WORKDIR /app

# Зависимости отдельным слоем, до появления кода: правка исходника не должна
# тянуть переустановку пакетов.
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

COPY tsconfig.json tsconfig.app.json tsconfig.node.json vite.config.ts index.html ./
COPY src ./src

# Сборка без `pnpm build`: проверка типов идёт отдельной командой на машине
# разработчика и в `pnpm check`, а образу нужна статика.
RUN pnpm exec vite build

FROM nginx:1.27-alpine AS serve

# Шаблон, а не готовый конфиг: образ nginx разворачивает `/etc/nginx/templates/*.template`
# в `/etc/nginx/conf.d/` при старте, подставляя окружение. Так адрес бэкенда задаётся
# при запуске и один образ годится любому контуру.
COPY docker/nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html

# Ключ установки доносится до браузера файлом, который рождается при старте контейнера,
# а не при сборке: в слоях образа секрета нет и быть не должно. Образ выполняет
# `/docker-entrypoint.d/*.sh` по порядку имён до запуска nginx; номер 40 ставит наш шаг
# после развёртывания шаблона конфигурации.
COPY docker/config-json.sh /docker-entrypoint.d/40-tracker-config-json.sh
RUN chmod +x /docker-entrypoint.d/40-tracker-config-json.sh

# Куда проксировать `/api`. Умолчание — сервис `api` контура сквозных тестов.
ENV TRACKER_API_URL=http://api:8000

# Подставляются только наши переменные: без фильтра `envsubst` съел бы `$uri`, `$host`
# и прочие переменные самого nginx, и конфигурация развалилась бы на старте.
ENV NGINX_ENVSUBST_FILTER=TRACKER_

EXPOSE 80
