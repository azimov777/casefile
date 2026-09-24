import userEvent from '@testing-library/user-event';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { say } from '@testing/say';
import { CopyEntryLink } from './copy-entry-link';

describe('ссылка на запись', () => {
  it('кладёт в буфер адрес карточки с номером записи и говорит, что скопировала', async () => {
    // `setup()` ставит буфер обмена user-event: в jsdom своего нет.
    const user = userEvent.setup();
    render(<CopyEntryLink taskKey="UI-124" no={16} />);

    await user.click(screen.getByRole('button', { name: say.ui('entry.copyLink', { no: 16 }) }));

    expect(await navigator.clipboard.readText()).toBe(
      `${window.location.origin}/tasks/UI-124?entry=16`,
    );
    expect(screen.getByRole('status')).toHaveTextContent(say.ui('entry.linkCopied'));
  });

  it('отказ буфера сказан словами на виду, а не проглочен', async () => {
    const user = userEvent.setup();
    vi.spyOn(navigator.clipboard, 'writeText').mockRejectedValue(
      new DOMException('Denied', 'NotAllowedError'),
    );
    render(<CopyEntryLink taskKey="UI-124" no={16} />);

    await user.click(screen.getByRole('button', { name: say.ui('entry.copyLink', { no: 16 }) }));

    const status = await screen.findByRole('status');
    expect(status).toHaveTextContent(say.ui('entry.clipboardUnavailable'));
    expect(status).not.toHaveClass('sr-only');
  });
});
