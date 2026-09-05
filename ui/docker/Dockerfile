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

COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
