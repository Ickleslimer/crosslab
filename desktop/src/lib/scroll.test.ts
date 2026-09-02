import { describe, it, expect } from 'vitest';
import { isNearBottom, shouldAutoScroll } from './scroll';

function mockContainer(scrollTop: number, scrollHeight: number, clientHeight: number): HTMLElement {
  return {
    scrollTop,
    scrollHeight,
    clientHeight
  } as HTMLElement;
}

describe('scroll helpers', () => {
  it('detects near bottom', () => {
    expect(isNearBottom(mockContainer(950, 1000, 100))).toBe(true);
    expect(isNearBottom(mockContainer(100, 1000, 100))).toBe(false);
  });

  it('auto-scrolls only when near bottom and new items arrive', () => {
    const nearBottom = mockContainer(950, 1000, 100);
    const scrolledUp = mockContainer(100, 1000, 100);
    expect(shouldAutoScroll(nearBottom, 5, 6)).toBe(true);
    expect(shouldAutoScroll(scrolledUp, 5, 6)).toBe(false);
    expect(shouldAutoScroll(nearBottom, 5, 5)).toBe(false);
  });
});
