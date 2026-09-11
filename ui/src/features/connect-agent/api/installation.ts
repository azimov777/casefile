import { queryOptions } from '@tanstack/react-query';
import { apiClient, unwrap, type components } from '@/shared/api';

export type Installation = components['schemas']['InstallationRead'];

export const installationKeys = {
  installation: ['installation'] as const,
};

/**
 * Сведения установки: адрес MCP, по которому к ней подключается агент.
 *
 * Открыт любому набору, в том числе `task`: экрану подключения нужен ровно тот ключ,
 * который у интерфейса уже есть. Адрес берётся как есть — интерфейс не дописывает
 * путь и не собирает его из адреса страницы: за прокси и на другой машине они
 * расходятся (`docs/FRONTEND.md`, «Адрес MCP»).
 */
export function installationQueryOptions() {
  return queryOptions({
    queryKey: installationKeys.installation,
    queryFn: () => unwrap(apiClient.GET('/api/v1/installation')),
    // Ответ меняется только с перезапуском установки, и контракт разрешает держать его
    // всю жизнь вкладки: перечитывать его по фокусу окна незачем.
    staleTime: Infinity,
  });
}
