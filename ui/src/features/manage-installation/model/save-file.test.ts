import { describe, expect, it, vi } from 'vitest';
import { archiveFilename, saveJsonFile } from './save-file';

describe('archiveFilename', () => {
  it('называет файл датой с ведущими нулями', () => {
    expect(archiveFilename(new Date(2026, 0, 5))).toBe('casefile-archive-2026-01-05.json');
    expect(archiveFilename(new Date(2026, 10, 23))).toBe('casefile-archive-2026-11-23.json');
  });
});

describe('saveJsonFile', () => {
  it('создаёт ссылку на объект, кликает по ней с нужным именем и освобождает адрес', async () => {
    const url = 'blob:mock-url';
    const createObjectURL = vi.spyOn(URL, 'createObjectURL').mockReturnValue(url);
    const revokeObjectURL = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});

    saveJsonFile({ hello: 'world' }, 'casefile-archive-2026-09-23.json');

    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(click).toHaveBeenCalledTimes(1);
    const link = click.mock.instances[0] as unknown as HTMLAnchorElement;
    expect(link.href).toBe(url);
    expect(link.download).toBe('casefile-archive-2026-09-23.json');
    // Освобождение отложено (`setTimeout(0)`), а не отсутствует: до этой строки
    // микрозадачам и макрозадачам ходу не было.
    expect(revokeObjectURL).not.toHaveBeenCalled();

    // Тело — сериализованное значение, а не строка по месту: сохраняется ровно то,
    // что попросили сохранить. Проверка асинхронна сама (`Blob.text()`), поэтому идёт
    // последней — после неё событийный цикл уже мог отпустить отложенный `revokeObjectURL`.
    const [blob] = createObjectURL.mock.calls[0]!;
    expect(blob).toBeInstanceOf(Blob);
    expect(await (blob as Blob).text()).toBe(JSON.stringify({ hello: 'world' }, null, 2));

    await vi.waitFor(() => expect(revokeObjectURL).toHaveBeenCalledWith(url));

    createObjectURL.mockRestore();
    revokeObjectURL.mockRestore();
    click.mockRestore();
  });
});
