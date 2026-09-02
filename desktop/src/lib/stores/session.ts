import { writable } from 'svelte/store';
import type { HealthResponse, SessionConfig } from '$lib/api/client';

export const sessionConfig = writable<SessionConfig | null>(null);
export const nodeHealth = writable<HealthResponse | null>(null);
export const nodePort = writable<number | null>(null);
