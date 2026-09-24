# src/pages/project/ui

## Файлы

- `project-page.tsx` — сборка экрана: ключ, название, описание, переход к задачам проекта; слева атрибуты, справа дело; `project_not_found` словами; состояние `entry` и `attribute` в адресе
- `project-attributes.tsx` — атрибуты: имя кнопкой и нынешнее значение текстом как есть; история атрибута по клику — записи `attribute_created`/`attribute_changed`/`attribute_removed` дела проекта с этим именем карточками `EntryCard`
- `project-case.tsx` — дело проекта описью `EntryIndex` (владелец — проект): строки из записей `GET /projects/{key}/entries`, тело по клику, следующая страница по кнопке
- `project-page.test.tsx` — карточка, атрибуты, история по клику, опись и тело, адрес восстанавливает раскрытое, `aria-current` в панели, `project_not_found`
