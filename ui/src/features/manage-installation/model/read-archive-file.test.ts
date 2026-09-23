import { describe, expect, it } from 'vitest';
import { ApiError } from '@/shared/api';
import { readArchiveFile } from './read-archive-file';

describe('readArchiveFile', () => {
  it('разбирает файл как JSON без единой правки', async () => {
    const body = { data: { format: 'casefile.installation-archive', tables: [] } };
    const file = new File([JSON.stringify(body)], 'casefile-archive-2026-09-23.json', {
      type: 'application/json',
    });

    await expect(readArchiveFile(file)).resolves.toEqual(body);
  });

  it('файл, который не JSON, — тот же код, что у бэкенда на нечитаемый архив', async () => {
    const file = new File(['не json вовсе'], 'notes.txt', { type: 'text/plain' });

    const error: unknown = await readArchiveFile(file).catch((cause: unknown) => cause);

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).code).toBe('archive_format_unsupported');
  });
});
