<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { createApi } from '$lib/api/client';
  import type { AgentPeer, Hypothesis, MessageEnvelope, RunRecord } from '$lib/api/client';
  import HeaderBar from '$lib/components/HeaderBar.svelte';
  import PeersList from '$lib/components/PeersList.svelte';
  import ChatFeed from '$lib/components/ChatFeed.svelte';
  import HypothesesPanel from '$lib/components/HypothesesPanel.svelte';
  import RunsPanel from '$lib/components/RunsPanel.svelte';
  import TranscriptPanel from '$lib/components/TranscriptPanel.svelte';
  import { connectNodeEvents, startPolling } from '$lib/sse';
  import { stopNode } from '$lib/tauri';
  import { nodeHealth, nodePort, sessionConfig } from '$lib/stores/session';

  let port = $state<number | null>(null);
  let health = $state($nodeHealth);
  let config = $state($sessionConfig);
  let peers = $state<AgentPeer[]>([]);
  let messages = $state<MessageEnvelope[]>([]);
  let hypotheses = $state<Hypothesis[]>([]);
  let runs = $state<RunRecord[]>([]);
  let transcript = $state('');

  nodeHealth.subscribe((v) => (health = v));
  nodePort.subscribe((v) => (port = v));
  sessionConfig.subscribe((v) => (config = v));

  async function refreshAll(api: ReturnType<typeof createApi>) {
    const [p, m, h, r, t] = await Promise.all([
      api.peers(),
      api.messages(),
      api.hypotheses(),
      api.runs(),
      api.transcript()
    ]);
    peers = p;
    messages = m;
    hypotheses = h;
    runs = r;
    transcript = t;
  }

  onMount(() => {
    if (!port) {
      goto('/');
      return;
    }
    const api = createApi(port);
    refreshAll(api).catch(console.error);

    const onEvent = (data: Record<string, unknown>) => {
      const event = data.event as string | undefined;
      if (
        event === 'message' ||
        event === 'peer_joined' ||
        event === 'peer_left' ||
        event === 'hypothesis_proposed' ||
        event === 'evidence_added' ||
        event === 'run_recorded' ||
        event === 'sync_signal' ||
        event === 'observation_added'
      ) {
        refreshAll(api).catch(console.error);
      }
    };

    connectNodeEvents(api.eventsUrl(), onEvent);
    startPolling(() => refreshAll(api).catch(console.error), 3000);

    return () => {};
  });

  async function sendChat(text: string) {
    if (!port || !config) return;
    const api = createApi(port);
    await api.sendChat(`human-${config.role}`, text);
    messages = await api.messages();
  }

  async function handleStop() {
    await stopNode();
    nodeHealth.set(null);
    nodePort.set(null);
    sessionConfig.set(null);
    await goto('/');
  }

  async function refreshTranscript() {
    if (!port) return;
    transcript = await createApi(port).transcript();
  }
</script>

{#if port}
  <div class="min-h-screen p-4 md:p-6 flex flex-col">
    <HeaderBar {health} {port} onStop={handleStop} />
    <main class="grid grid-cols-1 lg:grid-cols-3 gap-6 flex-grow">
      <section class="flex flex-col space-y-6">
        <PeersList {peers} />
        <ChatFeed {messages} role={config?.role ?? 'host'} onSend={sendChat} />
      </section>
      <HypothesesPanel {hypotheses} />
      <section class="space-y-4">
        <RunsPanel {runs} />
        <TranscriptPanel content={transcript} onRefresh={refreshTranscript} />
      </section>
    </main>
  </div>
{/if}
