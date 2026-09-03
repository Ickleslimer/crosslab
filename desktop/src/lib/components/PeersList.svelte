<script lang="ts">
  import type { AgentPeer } from '$lib/api/client';

  let { peers = [] }: { peers?: AgentPeer[] } = $props();

  function profileLabel(peer: AgentPeer): string | null {
    const profile = peer.metadata?.agent_profile;
    const harness = peer.harness ?? profile?.harness;
    const model = peer.model_display ?? profile?.model_display ?? peer.model_id ?? profile?.model_id;
    const confidence = peer.profile_confidence ?? profile?.confidence ?? 1.0;
    if (!harness && !model) return null;
    const prefix = confidence < 1 ? '~' : '';
    if (harness && model) return `${prefix}${harness} · ${model}`;
    return `${prefix}${harness ?? model}`;
  }
</script>

<div class="glass-panel rounded-xl p-4">
  <h2 class="text-sm font-semibold uppercase tracking-wider text-gray-400 mb-3">Connected Peer Nodes</h2>
  <div class="space-y-2">
    {#if peers.length === 0}
      <div class="text-xs text-gray-500 italic">No remote peers connected.</div>
    {:else}
      {#each peers as peer (peer.agent_id)}
        <div class="p-2.5 rounded bg-gray-900/90 border border-gray-800 flex justify-between items-center text-xs">
          <div>
            <div class="font-bold text-white flex items-center gap-1.5">
              <span class="w-2 h-2 rounded-full {peer.role === 'host' ? 'bg-blue-400' : 'bg-purple-400'}"></span>
              {peer.agent_id}
            </div>
            {#if profileLabel(peer)}
              <div class="text-cyan-300/90 text-[11px] mt-0.5">{profileLabel(peer)}</div>
            {/if}
            <div class="text-gray-400 text-[11px]">{peer.endpoint_url}</div>
            {#if peer.topology_warning}
              <div class="text-amber-400 text-[10px] mt-1">{peer.topology_warning}</div>
            {/if}
          </div>
          <div class="text-right">
            <span class="px-2 py-0.5 rounded text-[10px] uppercase font-semibold {peer.role === 'host' ? 'bg-blue-900/60 text-blue-300' : 'bg-purple-900/60 text-purple-300'}">
              {peer.role}
            </span>
            <div class="text-[10px] text-gray-500 mt-1">Offset: {(peer.clock_offset_ms ?? 0).toFixed(1)} ms</div>
          </div>
        </div>
      {/each}
    {/if}
  </div>
</div>
