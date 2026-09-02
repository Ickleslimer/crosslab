<script lang="ts">
  import type { HealthResponse } from '$lib/api/client';
  import { openLegacyDashboard, openLegacyInBrowser } from '$lib/tauri';

  let {
    health,
    port,
    onStop
  }: {
    health: HealthResponse | null;
    port: number;
    onStop: () => void;
  } = $props();

  async function openClassic() {
    await openLegacyDashboard(port);
  }

  async function openBrowser() {
    await openLegacyInBrowser(port);
  }
</script>

<header class="flex flex-wrap justify-between items-center pb-4 mb-6 border-b border-gray-800">
  <div class="flex items-center space-x-3">
    <div class="w-4 h-4 rounded-full bg-emerald-500 animate-pulse"></div>
    <h1 class="text-2xl font-bold tracking-tight text-white">CrossLab <span class="text-xs px-2 py-0.5 rounded bg-blue-900/60 text-blue-300 border border-blue-700">Desktop</span></h1>
  </div>
  <div class="flex flex-wrap items-center gap-2 text-sm mt-2 md:mt-0">
    {#if health?.session_id}
      <span class="px-3 py-1 rounded-full bg-gray-800 border border-gray-700">
        Join Code: <strong class="font-mono">{health.session_id}</strong>
        <button class="ml-2 text-blue-300 hover:text-blue-200 text-xs" onclick={() => navigator.clipboard.writeText(health.session_id)}>Copy</button>
      </span>
    {/if}
    <span class="px-3 py-1 rounded-full bg-purple-900/50 border border-purple-700">Role: <strong>{health?.role ?? '...'}</strong></span>
    <span class="px-3 py-1 rounded-full bg-blue-900/50 border border-blue-700">Node: <strong>{health?.agent_id ?? '...'}</strong></span>
    <button class="px-3 py-1 rounded bg-indigo-700 hover:bg-indigo-600 text-xs" onclick={openClassic} disabled={!health}>
      Classic HUD
    </button>
    <button class="px-3 py-1 rounded bg-gray-800 hover:bg-gray-700 text-xs border border-gray-700" onclick={openBrowser} disabled={!health}>
      Open in Browser
    </button>
    <button class="px-3 py-1 rounded bg-rose-900/70 hover:bg-rose-800 text-xs border border-rose-700" onclick={onStop}>
      Stop Session
    </button>
  </div>
</header>
