import { Store } from '@tauri-apps/plugin-store';
import type { SessionConfig } from '$lib/api/client';
import type { SessionManifestEntry } from '$lib/tauri';

const STORE_FILE = 'session.json';
const MANIFEST_KEY = 'manifest';

export async function loadSessionManifest(): Promise<SessionManifestEntry[]> {
  try {
    const store = await Store.load(STORE_FILE);
    const manifest = await store.get<SessionManifestEntry[]>(MANIFEST_KEY);
    return manifest ?? [];
  } catch {
    return [];
  }
}

export async function rememberSession(config: SessionConfig): Promise<void> {
  const store = await Store.load(STORE_FILE);
  const manifest = (await store.get<SessionManifestEntry[]>(MANIFEST_KEY)) ?? [];
  const entry: SessionManifestEntry = {
    ...config,
    joinCode: config.session,
    lastOpenedAt: Date.now()
  };
  const next = [entry, ...manifest.filter((item) => item.joinCode !== config.session)].slice(0, 12);
  await store.set(MANIFEST_KEY, next);
  await store.set('config', config);
  await store.save();
}

export function generateJoinCode(): string {
  const part = () => Math.random().toString(36).slice(2, 6).toUpperCase();
  return `XLAB-${part()}`;
}

export function formatRelativeTime(timestampMs: number): string {
  const delta = Date.now() - timestampMs;
  const minutes = Math.floor(delta / 60000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}
