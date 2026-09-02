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
  import RunbookPanel from '$lib/components/RunbookPanel.svelte';
  import TranscriptPanel from '$lib/components/TranscriptPanel.svelte';
  import type { RunbookItem } from '$lib/api/client';
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
  let runbookPending = $state<RunbookItem[]>([]);
  let transcript = $state('');
  let healthError = $state(false);

  nodeHealth.subscribe((v) => (health = v));
  nodePort.subscribe((v) => (port = v));
  sessionConfig.subscribe((v) => (config = v));

  async function refreshHealth(api: ReturnType<typeof createApi>) {
    try {
      const h = await api.health();
      health = h;
      nodeHealth.set(h);
      healthError = false;
    } catch {
      healthError = true;
    }
  }

  async function refreshAll(api: ReturnType<typeof createApi>) {
    const [p, m, h, r, t, rb] = await Promise.all([
      api.peers(),
      api.messages(),
      api.hypotheses(),
      api.runs(),
      api.transcript(),
      api.runbook()
    ]);
    peers = p;
    messages = m;
    hypotheses = h;
    runs = r;
    transcript = t;
    runbookPending = rb.pending ?? [];
  }

  onMount(() => {
    if (!port) {
      goto('/');
      return;
    }
    const api = createApi(port);
    refreshAll(api).catch(console.error);
    refreshHealth(api).catch(console.error);

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
    startPolling(() => refreshHealth(api).catch(console.error), 30000);

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

  async function handleHumanSignal(signal: string, detail: string, runId?: number) {
    if (!port || !config) return;
    const api = createApi(port);
    await api.humanSignal({
      run_id: runId ?? 0,
      signal,
      detail,
      human_role: config.role === 'client' ? 'client' : 'host'
    });
    await refreshAll(api);
  }

  async function refreshTranscript() {
    if (!port) return;
    transcript = await createApi(port).transcript();
  }
</script>

{#if port}
  <div class="min-h-screen p-4 md:p-6 flex flex-col">
    <HeaderBar {health} {healthError} {port} onStop={handleStop} />
    <main class="grid grid-cols-1 lg:grid-cols-3 gap-6 flex-grow">
      <section class="flex flex-col space-y-6">
        <PeersList {peers} />
        <ChatFeed {messages} role={config?.role ?? 'host'} onSend={sendChat} />
      </section>
      <HypothesesPanel {hypotheses} />
      <section class="space-y-4">
        <RunbookPanel pending={runbookPending} role={config?.role ?? 'host'} onSignal={handleHumanSignal} />
        <RunsPanel {runs} />
        <TranscriptPanel content={transcript} onRefresh={refreshTranscript} />
      </section>
    </main>
  </div>
{/if}
