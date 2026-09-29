# src/features/release-notice

Плашка внизу боковой панели: вышел выпуск Casefile новее этой установки (`TRK-416`).
Последний выпуск читает бэкенд с кэшем на час, вкладка — только свой API: при открытии
и раз в час. Кнопки «обновить» нет — обновляет служба `updater` установки.

## Папки

- `api/` — версия установки и последний выпуск: `GET /api/v1/installation/release`
- `ui/` — сама плашка со ссылкой на страницу выпуска

## Файлы

- `index.ts` — публичный интерфейс среза: `ReleaseNotice`, `releaseQueryOptions`, `releaseKeys`, `RELEASE_REFRESH_MS`, тип `ReleaseState`
