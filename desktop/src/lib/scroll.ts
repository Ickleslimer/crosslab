const DEFAULT_THRESHOLD = 50;

export function isNearBottom(container: HTMLElement, thresholdPx = DEFAULT_THRESHOLD): boolean {
  const distance = container.scrollHeight - container.scrollTop - container.clientHeight;
  return distance <= thresholdPx;
}

export function shouldAutoScroll(
  container: HTMLElement,
  previousCount: number,
  nextCount: number,
  thresholdPx = DEFAULT_THRESHOLD
): boolean {
  if (nextCount > previousCount) {
    return isNearBottom(container, thresholdPx);
  }
  return false;
}

export async function preserveScroll(
  container: HTMLElement,
  update: () => void | Promise<void>,
  options?: { forceBottom?: boolean; previousCount?: number; nextCount?: number }
): Promise<void> {
  const wasNearBottom = isNearBottom(container);
  const scrollTop = container.scrollTop;
  const scrollHeight = container.scrollHeight;
  await update();
  requestAnimationFrame(() => {
    const forceBottom =
      options?.forceBottom ||
      (options?.previousCount !== undefined &&
        options?.nextCount !== undefined &&
        shouldAutoScroll(container, options.previousCount, options.nextCount));
    if (forceBottom || wasNearBottom) {
      container.scrollTop = container.scrollHeight;
      return;
    }
    const heightDelta = container.scrollHeight - scrollHeight;
    container.scrollTop = scrollTop + heightDelta;
  });
}
