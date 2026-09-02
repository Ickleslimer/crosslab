<script lang="ts">
  import type { RunbookItem } from '$lib/api/client';

  let {
    pending = [],
    role = 'host',
    onSignal
  }: {
    pending?: RunbookItem[];
    role?: 'host' | 'client';
    onSignal?: (signal: string, detail: string, runId?: number) => void | Promise<void>;
  } = $props();
</script>

<div class="glass-panel rounded-xl p-4 flex flex-col space-y-3">
  <h2 class="text-sm font-semibold uppercase tracking-wider text-gray-400">Human Runbook</h2>
  {#if pending.length === 0}
    <p class="text-xs text-gray-500 italic">No pending human reproduction steps.</p>
  {:else}
    <ul class="space-y-3">
      {#each pending as item (item.message_id)}
        <li class="p-3 rounded-lg bg-gray-900 border border-amber-800/50 space-y-2">
          <div class="text-xs font-bold text-amber-300">{item.title}{item.run_id != null ? ` (Run #${item.run_id})` : ''}</div>
          <ol class="list-decimal list-inside text-[11px] text-gray-300 space-y-1">
            {#each item.steps as step, i (i)}
              <li><span class="text-gray-500">[{step.role}]</span> {step.instruction}</li>
            {/each}
          </ol>
          <div class="flex gap-2 pt-1">
            <button
              class="text-[10px] bg-rose-900/50 hover:bg-rose-800/60 border border-rose-700 px-2 py-1 rounded"
              onclick={() => onSignal?.('disconnect', 'Disconnect reported by human operator', item.run_id ?? undefined)}
            >Report disconnect</button>
            <button
              class="text-[10px] bg-amber-900/50 hover:bg-amber-800/60 border border-amber-700 px-2 py-1 rounded"
              onclick={() => onSignal?.('error_dialog', 'Error dialog observed', item.run_id ?? undefined)}
            >Report error dialog</button>
          </div>
        </li>
      {/each}
    </ul>
  {/if}
</div>
