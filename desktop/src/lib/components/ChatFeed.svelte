<script lang="ts">
  import { tick } from 'svelte';
  import type { MessageEnvelope } from '$lib/api/client';
  import { preserveScroll } from '$lib/scroll';

  let {
    messages = [],
    role = 'host',
    onSend
  }: {
    messages?: MessageEnvelope[];
    role?: string;
    onSend: (text: string) => Promise<void>;
  } = $props();

  let input = $state('');
  let container: HTMLDivElement | undefined = $state();
  let previousCount = $state(0);
  let forceBottom = $state(false);

  function badgeFor(senderId: string): { label: string; color: string } {
    const sid = senderId.toLowerCase();
    if (sid.includes('human') || sid.includes('operator')) {
      if (sid.includes('host')) return { label: 'Human (Host)', color: 'bg-emerald-900/60 text-emerald-300 border-emerald-600' };
      if (sid.includes('client')) return { label: 'Human (Client)', color: 'bg-amber-900/60 text-amber-300 border-amber-600' };
      return { label: 'Human Operator', color: 'bg-emerald-900/60 text-emerald-300 border-emerald-600' };
    }
    if (sid.includes('host')) return { label: 'Agent A (Host)', color: 'bg-blue-900/50 text-blue-300 border-blue-700' };
    if (sid.includes('client')) return { label: 'Agent B (Client)', color: 'bg-purple-900/50 text-purple-300 border-purple-700' };
    return { label: senderId, color: 'bg-gray-800 text-gray-300 border-gray-700' };
  }

  $effect(() => {
    if (!container) return;
    const nextCount = messages.length;
    preserveScroll(
      container,
      async () => {
        await tick();
      },
      { forceBottom, previousCount, nextCount }
    );
    previousCount = nextCount;
    forceBottom = false;
  });

  async function send() {
    const text = input.trim();
    if (!text) return;
    input = '';
    forceBottom = true;
    await onSend(text);
  }
</script>

<div class="glass-panel rounded-xl p-4 flex flex-col min-h-[350px]">
  <h2 class="text-sm font-semibold uppercase tracking-wider text-gray-400 mb-3 flex justify-between">
    <span>A2A Agent Dialogue</span>
    <span class="text-xs text-emerald-400">LIVE</span>
  </h2>
  <div bind:this={container} class="flex-grow space-y-3 overflow-y-auto max-h-[380px] pr-2 text-xs">
    {#if messages.length === 0}
      <div class="text-xs text-gray-500 italic">No messages yet.</div>
    {:else}
      {#each messages as msg (msg.message_id)}
        {@const badge = badgeFor(msg.sender_id)}
        <div class="p-2.5 rounded bg-gray-900/80 border border-gray-800 space-y-1">
          <div class="flex justify-between items-center text-[10px] text-gray-400">
            <span class="font-semibold px-1.5 py-0.5 rounded border {badge.color}">{badge.label}</span>
            <span>{msg.timestamp ? msg.timestamp.split('T')[1]?.slice(0, 8) : ''}</span>
          </div>
          <div class="text-gray-200 mt-1">{msg.natural_language ?? JSON.stringify(msg.payload)}</div>
        </div>
      {/each}
    {/if}
  </div>
  <div class="mt-3 pt-3 border-t border-gray-800 flex gap-2">
    <input
      bind:value={input}
      class="flex-grow bg-gray-900 border border-gray-700 rounded px-3 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500"
      placeholder="Send reasoning to peer agents..."
      onkeydown={(e) => e.key === 'Enter' && send()}
    />
    <button class="bg-blue-600 hover:bg-blue-500 text-white px-3 py-1.5 rounded text-xs" onclick={send}>Send</button>
  </div>
</div>
