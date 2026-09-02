<script lang="ts">
  import { tick } from 'svelte';
  import { preserveScroll } from '$lib/scroll';

  let {
    content = '',
    onRefresh
  }: {
    content?: string;
    onRefresh: () => Promise<void>;
  } = $props();

  let container: HTMLDivElement | undefined = $state();
  let previousLength = $state(0);

  $effect(() => {
    if (!container) return;
    const nextLength = content.length;
    preserveScroll(container, async () => tick(), { previousCount: previousLength, nextCount: nextLength });
    previousLength = nextLength;
  });
</script>

<div class="glass-panel rounded-xl p-4 flex flex-col">
  <div class="flex justify-between items-center mb-3">
    <h2 class="text-sm font-semibold uppercase tracking-wider text-gray-400">Session Transcript</h2>
    <button class="text-xs bg-gray-800 hover:bg-gray-700 px-2 py-1 rounded border border-gray-700" onclick={onRefresh}>
      Refresh
    </button>
  </div>
  <div bind:this={container} class="overflow-y-auto max-h-[240px] text-[11px] text-gray-300 whitespace-pre-wrap bg-gray-950 border border-gray-800 rounded p-3">
    {content || 'Transcript will appear here once the session has activity.'}
  </div>
</div>
