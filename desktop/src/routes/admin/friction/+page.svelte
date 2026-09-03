<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { createApi, type FrictionHeatmap } from '$lib/api/client';
  import { nodePort } from '$lib/stores/session';

  let port = $state<number | null>(null);
  let heatmap = $state<FrictionHeatmap | null>(null);
  let error = $state('');

  nodePort.subscribe((v) => (port = v));

  function cellIntensity(count: number, max: number): string {
    if (count === 0) return 'bg-gray-900/40';
    const ratio = count / Math.max(max, 1);
    if (ratio >= 0.75) return 'bg-rose-700/80';
    if (ratio >= 0.5) return 'bg-amber-600/70';
    if (ratio >= 0.25) return 'bg-blue-700/60';
    return 'bg-emerald-800/50';
  }

  function cellTitle(tax: string, harness: string): string {
    const events = heatmap?.cells?.[tax]?.[harness] ?? [];
    if (!events.length) return 'No events';
    return events.map((e) => `${e.id} (${e.status}, ${e.severity})`).join('\n');
  }

  const maxCount = $derived(() => {
    if (!heatmap) return 1;
    return Math.max(1, ...heatmap.matrix.flat());
  });

  onMount(async () => {
    if (!port) {
      await goto('/');
      return;
    }
    try {
      heatmap = await createApi(port).frictionHeatmap();
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    }
  });
</script>

<div class="min-h-screen p-4 md:p-6 text-white">
  <header class="flex flex-wrap items-center justify-between gap-3 mb-6 pb-4 border-b border-gray-800">
    <div>
      <h1 class="text-2xl font-bold">Friction Heatmap</h1>
      <p class="text-sm text-gray-400">Harness × taxonomy matrix from friction study events</p>
    </div>
    <button class="px-3 py-1 rounded bg-gray-800 hover:bg-gray-700 text-sm border border-gray-700" onclick={() => goto('/session')}>
      Back to session
    </button>
  </header>

  {#if error}
    <p class="text-rose-400">{error}</p>
  {:else if heatmap}
    <div class="mb-4 flex flex-wrap gap-3 text-sm text-gray-300">
      <span>{heatmap.total_events} events</span>
      {#each Object.entries(heatmap.status_totals) as [status, count]}
        <span class="px-2 py-0.5 rounded bg-gray-800 border border-gray-700">{status}: {count}</span>
      {/each}
    </div>

    <div class="overflow-x-auto">
      <table class="min-w-full border-collapse text-sm">
        <thead>
          <tr>
            <th class="p-2 text-left text-gray-400 border border-gray-800">Taxonomy</th>
            {#each heatmap.harnesses as harness}
              <th class="p-2 text-center text-gray-300 border border-gray-800 capitalize">{harness}</th>
            {/each}
          </tr>
        </thead>
        <tbody>
          {#each heatmap.taxonomies as tax, rowIdx}
            <tr>
              <td class="p-2 font-mono text-xs text-gray-300 border border-gray-800">{tax}</td>
              {#each heatmap.harnesses as harness, colIdx}
                {@const count = heatmap.matrix[rowIdx][colIdx]}
                <td
                  class="p-2 text-center border border-gray-800 {cellIntensity(count, maxCount())}"
                  title={cellTitle(tax, harness)}
                >
                  {count || ''}
                </td>
              {/each}
            </tr>
          {/each}
        </tbody>
      </table>
    </div>

    <div class="mt-4 flex flex-wrap gap-3 text-xs text-gray-400">
      <span class="flex items-center gap-1"><span class="w-4 h-4 rounded bg-emerald-800/50 inline-block"></span> low</span>
      <span class="flex items-center gap-1"><span class="w-4 h-4 rounded bg-blue-700/60 inline-block"></span> medium</span>
      <span class="flex items-center gap-1"><span class="w-4 h-4 rounded bg-amber-600/70 inline-block"></span> high</span>
      <span class="flex items-center gap-1"><span class="w-4 h-4 rounded bg-rose-700/80 inline-block"></span> critical density</span>
    </div>
  {:else}
    <p class="text-gray-400">Loading heatmap…</p>
  {/if}
</div>
