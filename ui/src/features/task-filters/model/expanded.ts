import { useCallback, useState } from 'react';

/**
 * Развёрнута ли форма отбора. Единственное состояние экрана списка, которое живёт
 * не в адресе, а в хранилище браузера.
 *
 * Причина в том, что это состояние **человека**, а не выдачи: по пересланной ссылке
 * другой увидит те же строки независимо от того, была ли форма раскрыта, — значит
 * в адресе ему делать нечего (`CONCEPT.md`, 3). А помнить между визитами надо: тот,
 * кто отбирает часто, иначе разворачивал бы форму каждое утро заново.
 */
const STORAGE_KEY = 'tracker.filters.expanded';

/** Свёрнуто по умолчанию: первый экран списка принадлежит задачам, а не форме. */
function readExpanded(): boolean {
  try {
    return window.localStorage.getItem(STORAGE_KEY) === 'true';
  } catch {
    // Приватный режим и запрет на хранилище: форма работает, но забудет своё состояние.
    return false;
  }
}

function writeExpanded(value: boolean): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, String(value));
  } catch {
    // См. readExpanded.
  }
}

/**
 * Развёрнутость формы с памятью между визитами.
 *
 * `force` держит форму раскрытой, чего бы ни помнило хранилище: так приходит отказ
 * разбора запроса. Пришедший по чужой ссылке с опечаткой в запросе обязан увидеть
 * поле, в котором эта опечатка сделана, — иначе объяснение отказа указывало бы на
 * то, чего на экране нет.
 *
 * Выбор человека при этом не переписывается: снятый `force` возвращает форму к тому,
 * что он сам выбрал в прошлый раз.
 */
export function useFiltersExpanded(force: boolean): [boolean, (value: boolean) => void] {
  const [chosen, setChosen] = useState(readExpanded);

  const choose = useCallback((value: boolean) => {
    setChosen(value);
    writeExpanded(value);
  }, []);

  return [chosen || force, choose];
}
