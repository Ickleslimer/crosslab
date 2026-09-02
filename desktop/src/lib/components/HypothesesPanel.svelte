<script lang="ts">
  import { tick } from 'svelte';
  import type { Hypothesis } from '$lib/api/client';
  import { preserveScroll } from '$lib/scroll';

  let { hypotheses = [] }: { hypotheses?: Hypothesis[] } = $props();
  let container: HTMLDivElement | undefined = $state();
  let previousCount = $state(0);

  function statusColor(status: string): string {
    if (status === 'supported') return 'bg-emerald-900/60 text-emerald-300 border-emerald-700';
    if (status === 'contradicted') return 'bg-rose-900/60 text-rose-300 border-rose-700';
    return 'bg-amber-900/60 text-amber-300 border-amber-700';
  }

  $effect(() => {
    if (!container) return;
    const nextCount = hypotheses.length;
    preserveScroll(container, async () => tick(), { previousCount, nextCount });
    previousCount = nextCount;
  });
</script>

<div class="glass-panel rounded-xl p-4 flex flex-col">
  <h2 class="text-sm font-semibold uppercase tracking-wider text-gray-400 mb-3">Hypotheses & Evidence Graph</h2>
  <div bind:this={container} class="space-y-4 overflow-y-auto max-h-[700px] pr-2">
    {#if hypotheses.length === 0}
      <div class="text-xs text-gray-500 italic">No hypotheses proposed yet.</div>
    {:else}
      {#each hypotheses as hyp (hyp.id)}
        <div class="p-3 rounded-lg bg-gray-900 border border-gray-800 space-y-2">
          <div class="flex justify-between items-start">
            <div class="font-bold text-white text-xs">{hyp.title}</div>
            <span class="px-2 py-0.5 rounded text-[10px] font-semibold border uppercase {statusColor(hyp.status)}">{hyp.status}</span>
          </div>
          <p class="text-xs text-gray-400">{hyp.description}</p>
          {#if hyp.evidence_graph?.length}
            <div class="pt-2 border-t border-gray-800">
              <div class="text-[10px] uppercase font-bold text-gray-500">Evidence Graph ({hyp.evidence_graph.length})</div>
              <ul class="list-none pl-0 mt-1">
                {#each hyp.evidence_graph as ev, i (i)}
                  <li class="flex items-start gap-1.5 text-[11px] mt-1 text-gray-300">
                    <span class={ev.relation === 'supports' ? 'text-emerald-400' : 'text-rose-400'}>
                      {ev.relation === 'supports' ? '✓' : '✗'}
                    </span>
                    <span>[{ev.evidence_type.toUpperCase()}] {ev.rationale}</span>
                  </li>
                {/each}
              </ul>
            </div>
          {/if}
        </div>
      {/each}
    {/if}
  </div>
</div>
