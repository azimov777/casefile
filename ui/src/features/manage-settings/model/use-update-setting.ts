import { useMutation, useQueryClient } from '@tanstack/react-query';
import { settingKeys, type Setting } from '@/entities/setting';
import { updateSetting } from '../api/settings';

/**
 * Сохранить значение настройки или вернуть её окружению. Ответ — настройка целиком, как
 * в списке, и ложится в кэш на место прежней: экран показывает новое значение сразу, а
 * список перечитывается следом на случай, если рядом правил другой администратор.
 */
export function useUpdateSetting(name: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (value: string | null) => updateSetting(name, value),
    onSuccess: (changed) => {
      queryClient.setQueryData<Setting[]>(settingKeys.list, (items) =>
        items?.map((item) => (item.name === changed.name ? changed : item)),
      );
      void queryClient.invalidateQueries({ queryKey: settingKeys.list });
    },
  });
}
