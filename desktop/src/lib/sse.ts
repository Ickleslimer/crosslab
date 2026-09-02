import { onDestroy } from 'svelte';

export function connectNodeEvents(url: string, onEvent: (data: Record<string, unknown>) => void): () => void {
  const source = new EventSource(url);
  source.onmessage = (event) => {
    try {
      onEvent(JSON.parse(event.data));
    } catch {
      // ignore malformed events
    }
  };
  source.onerror = () => {
    // EventSource reconnects automatically
  };
  const cleanup = () => source.close();
  onDestroy(cleanup);
  return cleanup;
}

export function startPolling(callback: () => void, intervalMs: number): () => void {
  const id = setInterval(callback, intervalMs);
  const cleanup = () => clearInterval(id);
  onDestroy(cleanup);
  return cleanup;
}
