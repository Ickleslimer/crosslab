<script lang="ts">
  import { tick } from 'svelte';
  import type { RunRecord } from '$lib/api/client';
  import { preserveScroll } from '$lib/scroll';

  let { runs = [] }: { runs?: RunRecord[] } = $props();
  let container: HTMLDivElement | undefined = $state();
  let previousCount = $state(0);

  $effect(() => {
    if (!container) return;
    const nextCount = runs.length;
    preserveScroll(container, async () => tick(), { previousCount, nextCount });
    previousCount = nextCount;
  });
</script>

<div class="glass-panel rounded-xl p-4 flex flex-col space-y-4">
  <h2 class="text-sm font-semibold uppercase tracking-wider text-gray-400 mb-1">Multi-Machine Run Correlation</h2>
  <div bind:this={container} class="space-y-4 overflow-y-auto max-h-[700px] pr-2">
    {#if runs.length === 0}
      <div class="text-xs text-gray-500 italic">No synchronized test runs recorded yet.</div>
    {:else}
      {#each runs as run (run.run_id)}
        {@const discrepancies = run.correlated_findings?.discrepancies ?? []}
        <div class="p-3 rounded-lg bg-gray-900 border border-gray-800 space-y-2">
          <div class="flex justify-between items-center text-xs">
            <span class="font-bold text-blue-400">Run #{run.run_id} ({run.build ?? 'unknown'})</span>
            <span class="px-2 py-0.5 rounded text-[10px] uppercase font-semibold {run.outcome === 'reproduced' ? 'bg-rose-900/60 text-rose-300 border border-rose-700' : 'bg-gray-800 text-gray-300'}">
              {run.outcome}
            </span>
          </div>
          <div class="text-[11px] text-gray-400 flex justify-between">
            <span>Host Pkts: <strong>{run.host?.last_received_packet ?? 'N/A'}</strong></span>
            <span>Client Pkts: <strong>{run.client?.last_sent_packet ?? 'N/A'}</strong></span>
          </div>
          {#if discrepancies.length}
            <div class="pt-2 border-t border-gray-800 space-y-1">
              <div class="text-[10px] uppercase font-bold text-amber-400">Discrepancies Detected ({discrepancies.length})</div>
              {#each discrepancies as d, i (i)}
                <div class="text-[11px] text-gray-300 bg-gray-950 p-2 rounded border border-gray-800">
                  <div class="font-semibold text-yellow-300 text-[10px]">{d.code}</div>
                  <div>{d.description}</div>
                </div>
              {/each}
            </div>
          {/if}
        </div>
      {/each}
    {/if}
  </div>
</div>
