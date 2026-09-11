import userEvent from '@testing-library/user-event';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { say } from '@testing/say';
import { CopyBlock } from './copy-block';

const LABEL = 'Claude Code command';
const TEXT = 'claude mcp add --transport http --scope user casefile "https://mcp.example.test/mcp"';

describe('текст для копирования', () => {
  it('кнопка кладёт в буфер ровно текст блока и говорит, что скопировала', async () => {
    // `setup()` ставит буфер обмена user-event: в jsdom своего нет.
    const user = userEvent.setup();
    render(<CopyBlock label={LABEL} caption="Terminal" text={TEXT} />);

    // Текст виден целиком, без переносов, которых нет в самом тексте.
    expect(screen.getByText(TEXT)).toBeInTheDocument();
    // Подпись — прямой потомок `figure`: только такой `figcaption` даёт блоку имя. Само
    // имя jsdom по подписи не считает — его находит браузер (`e2e/connect.spec.ts`).
    const caption = screen.getByText('Terminal');
    expect(caption.tagName).toBe('FIGCAPTION');
    expect(caption.parentElement?.tagName).toBe('FIGURE');

    await user.click(
      screen.getByRole('button', { name: say.ui('copyBlock.label', { label: LABEL }) }),
    );

    expect(await navigator.clipboard.readText()).toBe(TEXT);
    // Имя кнопки идёт следом за видимой подписью, а удача объявлена вежливо.
    const button = screen.getByRole('button', {
      name: say.ui('copyBlock.copiedLabel', { label: LABEL }),
    });
    expect(button).toHaveTextContent(say.ui('copyBlock.copied'));
    expect(screen.getByRole('status')).toHaveTextContent(
      say.ui('copyBlock.done', { label: LABEL }),
    );
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('отказ буфера сказан словами на виду, а не проглочен', async () => {
    const user = userEvent.setup();
    const refuse = vi
      .spyOn(navigator.clipboard, 'writeText')
      .mockRejectedValue(new DOMException('Denied', 'NotAllowedError'));
    render(<CopyBlock label={LABEL} caption="Terminal" text={TEXT} />);

    await user.click(
      screen.getByRole('button', { name: say.ui('copyBlock.label', { label: LABEL }) }),
    );

    expect(refuse).toHaveBeenCalledWith(TEXT);
    expect(await screen.findByRole('alert')).toHaveTextContent(say.ui('copyBlock.failed'));
    // Кнопка не утверждает, что скопировала: имя прежнее.
    expect(
      screen.getByRole('button', { name: say.ui('copyBlock.label', { label: LABEL }) }),
    ).toHaveTextContent(say.ui('copyBlock.action'));
    expect(screen.getByRole('status')).toBeEmptyDOMElement();
  });

  it('новый текст снимает отметку о прежнем: скопировано было не оно', async () => {
    const user = userEvent.setup();
    const { rerender } = render(<CopyBlock label={LABEL} caption="Terminal" text={TEXT} />);

    await user.click(
      screen.getByRole('button', { name: say.ui('copyBlock.label', { label: LABEL }) }),
    );
    expect(
      screen.getByRole('button', { name: say.ui('copyBlock.copiedLabel', { label: LABEL }) }),
    ).toBeInTheDocument();

    rerender(<CopyBlock label={LABEL} caption="Terminal" text={`${TEXT} --header "X"`} />);

    expect(
      screen.getByRole('button', { name: say.ui('copyBlock.label', { label: LABEL }) }),
    ).toHaveTextContent(say.ui('copyBlock.action'));
    expect(screen.getByRole('status')).toBeEmptyDOMElement();
  });
});
