import { describe, expect, it } from 'vitest';
import { splitSize } from './format-bytes';

describe('splitSize', () => {
  it('держит байты, пока не набралась тысяча двадцать четыре', () => {
    expect(splitSize(0)).toEqual({ value: 0, step: 'bytes' });
    expect(splitSize(1023)).toEqual({ value: 1023, step: 'bytes' });
  });

  it('переходит на следующую ступень ровно на степенях 1024', () => {
    expect(splitSize(1024)).toEqual({ value: 1, step: 'kilobytes' });
    expect(splitSize(1_572_864)).toEqual({ value: 1.5, step: 'megabytes' });
    expect(splitSize(1024 ** 3)).toEqual({ value: 1, step: 'gigabytes' });
  });

  it('не выходит за гигабайты', () => {
    expect(splitSize(5 * 1024 ** 4)).toEqual({ value: 5120, step: 'gigabytes' });
  });
});
