import { invoke } from '@tauri-apps/api/core';
import type { HealthResponse, SessionConfig } from '$lib/api/client';

export interface NetworkEndpoint {
  ip: string;
  interface: string;
  kind: 'lan' | 'virtual' | 'link_local' | 'other' | string;
  label: string;
  recommended: boolean;
}

export interface SavedSession {
  joinCode: string;
  updatedAt: number;
  hasTranscript: boolean;
}

export interface SessionManifestEntry extends SessionConfig {
  joinCode: string;
  lastOpenedAt: number;
}

export async function startNode(config: SessionConfig): Promise<HealthResponse> {
  return invoke<HealthResponse>('start_node', {
    config: {
      role: config.role,
      session: config.session,
      port: config.port,
      peer: config.peer ?? null,
      agentId: config.agentId ?? null
    }
  });
}

export async function stopNode(): Promise<void> {
  return invoke('stop_node');
}

export async function getNodePort(): Promise<number | null> {
  return invoke<number | null>('get_node_port');
}

export async function getLocalAddresses(): Promise<NetworkEndpoint[]> {
  return invoke<NetworkEndpoint[]>('get_local_addresses');
}

export async function listSavedSessions(): Promise<SavedSession[]> {
  return invoke<SavedSession[]>('list_saved_sessions');
}

export async function openDataFolder(): Promise<void> {
  return invoke('open_data_folder');
}

export async function openLegacyDashboard(port: number): Promise<void> {
  return invoke('open_legacy_dashboard', { port });
}

export async function openLegacyInBrowser(port: number): Promise<void> {
  return invoke('open_legacy_in_browser', { port });
}
