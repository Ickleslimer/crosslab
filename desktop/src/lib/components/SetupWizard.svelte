<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import type { AgentRole, SessionConfig } from '$lib/api/client';
  import { getLocalAddresses, getNodePort, listSavedSessions, startNode, type NetworkEndpoint, type SavedSession } from '$lib/tauri';
  import { formatRelativeTime, generateJoinCode, loadSessionManifest, rememberSession, type SessionManifestEntry } from '$lib/sessions';
  import { nodeHealth, nodePort, sessionConfig } from '$lib/stores/session';

  let role: AgentRole = $state('host');
  let joinCode = $state('fear3-debug');
  let port = $state(8765);
  let peer = $state('http://127.0.0.1:8765');
  let endpoints = $state<NetworkEndpoint[]>([]);
  let savedSessions = $state<SavedSession[]>([]);
  let manifest = $state<SessionManifestEntry[]>([]);
  let showAdvanced = $state(false);
  let loading = $state(false);
  let error = $state('');

  const recommended = $derived(endpoints.find((endpoint) => endpoint.recommended));
  const advancedEndpoints = $derived(endpoints.filter((endpoint) => !endpoint.recommended));

  const recentSessions = $derived(
    savedSessions.map((saved) => {
      const meta = manifest.find((entry) => entry.joinCode === saved.joinCode);
      return { saved, meta };
    })
  );

  onMount(async () => {
    endpoints = await getLocalAddresses();
    savedSessions = await listSavedSessions();
    manifest = await loadSessionManifest();

    const existingPort = await getNodePort();
    if (existingPort) {
      goto('/session');
      return;
    }

    const latest = manifest[0];
    if (latest) {
      role = latest.role;
      joinCode = latest.joinCode;
      port = latest.port;
      peer = latest.peer ?? peer;
    }
  });

  function onRoleChange(next: AgentRole) {
    role = next;
    port = next === 'host' ? 8765 : 8766;
  }

  function hostUrlFor(ip: string): string {
    return `http://${ip}:${port}`;
  }

  async function copyText(text: string) {
    await navigator.clipboard.writeText(text);
  }

  async function resumeSession(entry: SessionManifestEntry | undefined, code: string) {
    const nextRole = entry?.role ?? role;
    const nextPort = entry?.port ?? port;
    const nextPeer = entry?.peer ?? peer;

    joinCode = code;
    role = nextRole;
    port = nextPort;
    peer = nextPeer;

    await startSession({
      role: nextRole,
      session: code,
      port: nextPort,
      peer: nextRole === 'client' ? nextPeer : undefined
    });
  }

  async function startSession(override?: SessionConfig) {
    loading = true;
    error = '';
    const config: SessionConfig = override ?? {
      role,
      session: joinCode.trim(),
      port,
      peer: role === 'client' ? peer : undefined
    };
    if (!config.session) {
      error = 'Join code is required.';
      loading = false;
      return;
    }
    try {
      const health = await startNode(config);
      nodeHealth.set(health);
      nodePort.set(port);
      sessionConfig.set(config);
      await rememberSession(config);
      await goto('/session');
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      loading = false;
    }
  }
</script>

<main class="min-h-screen p-6 max-w-3xl mx-auto">
  <h1 class="text-3xl font-bold text-white mb-2">CrossLab Desktop</h1>
  <p class="text-gray-400 mb-8 text-sm">
    Investigations persist locally. Rejoin with the same join code to pick up the transcript and history.
  </p>

  <div class="glass-panel rounded-xl p-6 space-y-6">
    {#if recentSessions.length > 0}
      <section class="space-y-3">
        <div>
          <h2 class="text-sm uppercase tracking-wider text-gray-400">Resume Investigation</h2>
          <p class="text-xs text-gray-500 mt-1">These sessions are saved on this machine. Use the same join code on both A and B.</p>
        </div>
        <ul class="space-y-2">
          {#each recentSessions as item (item.saved.joinCode)}
            <li class="flex items-center justify-between gap-3 bg-gray-900 border border-gray-800 rounded-lg px-3 py-2">
              <div class="min-w-0">
                <div class="font-mono text-sm text-white">{item.saved.joinCode}</div>
                <div class="text-[11px] text-gray-500 mt-1">
                  {#if item.meta}
                    Last role: {item.meta.role} · Port {item.meta.port}
                  {/if}
                  {#if item.saved.hasTranscript}
                    · Transcript saved
                  {/if}
                  · {formatRelativeTime(item.saved.updatedAt || item.meta?.lastOpenedAt || Date.now())}
                </div>
              </div>
              <button
                class="shrink-0 text-xs bg-gray-800 hover:bg-gray-700 disabled:opacity-50 border border-gray-700 px-3 py-1.5 rounded"
                disabled={loading}
                onclick={() => resumeSession(item.meta, item.saved.joinCode)}
              >
                {loading && joinCode === item.saved.joinCode ? 'Starting…' : 'Resume'}
              </button>
            </li>
          {/each}
        </ul>
      </section>
    {/if}

    <section>
      <h2 class="text-sm uppercase tracking-wider text-gray-400 mb-3">Role</h2>
      <div class="grid grid-cols-2 gap-3">
        <button
          class="p-4 rounded border text-left {role === 'host' ? 'border-blue-500 bg-blue-950/40' : 'border-gray-700 bg-gray-900'}"
          onclick={() => onRoleChange('host')}
        >
          <div class="font-bold text-white">Host (A)</div>
          <div class="text-xs text-gray-400 mt-1">Runs the host side and accepts client connections.</div>
        </button>
        <button
          class="p-4 rounded border text-left {role === 'client' ? 'border-purple-500 bg-purple-950/40' : 'border-gray-700 bg-gray-900'}"
          onclick={() => onRoleChange('client')}
        >
          <div class="font-bold text-white">Client (B)</div>
          <div class="text-xs text-gray-400 mt-1">Reconnects with the host URL and the same join code.</div>
        </button>
      </div>
    </section>

    <section class="grid grid-cols-1 md:grid-cols-2 gap-4">
      <label class="block text-sm">
        <span class="text-gray-400">Join Code</span>
        <div class="mt-1 flex gap-2">
          <input bind:value={joinCode} class="flex-grow bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm font-mono" />
          <button
            type="button"
            class="text-xs bg-gray-800 hover:bg-gray-700 border border-gray-700 px-3 rounded"
            onclick={() => (joinCode = generateJoinCode())}
          >
            New
          </button>
        </div>
        <p class="text-xs text-gray-500 mt-2">Both machines must use this exact code to share one investigation.</p>
      </label>
      <label class="block text-sm">
        <span class="text-gray-400">Port</span>
        <input type="number" bind:value={port} class="mt-1 w-full bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm" />
      </label>
    </section>

    {#if role === 'client'}
      <label class="block text-sm">
        <span class="text-gray-400">Host Peer URL</span>
        <input bind:value={peer} class="mt-1 w-full bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm" placeholder="http://192.168.1.10:8765" />
        <p class="text-xs text-gray-500 mt-2">
          Paste the host URL and enter join code <code class="text-gray-300">{joinCode}</code> — both must match the previous session.
        </p>
      </label>
    {:else}
      <section class="space-y-3">
        <div>
          <h2 class="text-sm uppercase tracking-wider text-gray-400">Share with Client</h2>
          <p class="text-xs text-gray-500 mt-1">Share the join code and one URL. The client needs both to reconnect to this investigation.</p>
        </div>

        <div class="rounded-lg border border-blue-800 bg-blue-950/20 p-4 space-y-2">
          <div class="flex items-center justify-between gap-3">
            <div>
              <div class="text-xs uppercase tracking-wider text-blue-300 font-semibold">Join Code</div>
              <code class="text-lg text-white font-mono">{joinCode}</code>
            </div>
            <button class="text-xs bg-blue-700 hover:bg-blue-600 px-3 py-1.5 rounded" onclick={() => copyText(joinCode)}>
              Copy Code
            </button>
          </div>
        </div>

        {#if recommended}
          <div class="rounded-lg border border-emerald-700 bg-emerald-950/30 p-4 space-y-2">
            <div class="flex items-center justify-between gap-3">
              <div>
                <div class="text-xs uppercase tracking-wider text-emerald-300 font-semibold">Host URL</div>
                <div class="text-[11px] text-emerald-200/80 mt-1">{recommended.label}</div>
              </div>
              <button
                class="bg-emerald-600 hover:bg-emerald-500 text-white px-3 py-1.5 rounded text-xs font-semibold"
                onclick={() => copyText(hostUrlFor(recommended.ip))}
              >
                Copy URL
              </button>
            </div>
            <code class="block text-sm text-white break-all">{hostUrlFor(recommended.ip)}</code>
          </div>
        {:else if endpoints.length === 0}
          <p class="text-xs text-gray-500">No LAN addresses detected. Same-machine testing can use <code>http://127.0.0.1:{port}</code>.</p>
        {:else}
          <p class="text-xs text-amber-300">No clear home LAN address found. Expand advanced options or use Tailscale / relay if machines are remote.</p>
        {/if}

        {#if advancedEndpoints.length > 0}
          <div class="border border-gray-800 rounded-lg overflow-hidden">
            <button
              class="w-full flex justify-between items-center px-3 py-2 text-xs text-gray-400 bg-gray-900 hover:bg-gray-800"
              onclick={() => (showAdvanced = !showAdvanced)}
            >
              <span>Other addresses ({advancedEndpoints.length}) — virtual / link-local</span>
              <span>{showAdvanced ? 'Hide' : 'Show'}</span>
            </button>
            {#if showAdvanced}
              <ul class="divide-y divide-gray-800">
                {#each advancedEndpoints as endpoint (endpoint.ip)}
                  <li class="px-3 py-2 text-xs bg-gray-950/60">
                    <div class="flex justify-between items-start gap-3">
                      <div>
                        <code class="text-gray-200">{hostUrlFor(endpoint.ip)}</code>
                        <div class="text-[11px] text-gray-500 mt-1">{endpoint.label}</div>
                      </div>
                      <button class="text-blue-300 hover:text-blue-200 shrink-0" onclick={() => copyText(hostUrlFor(endpoint.ip))}>Copy</button>
                    </div>
                  </li>
                {/each}
              </ul>
            {/if}
          </div>
        {/if}
      </section>
    {/if}

    {#if error}
      <p class="text-rose-300 text-sm">{error}</p>
    {/if}

    <button
      class="w-full bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white py-3 rounded font-semibold"
      disabled={loading}
      onclick={() => startSession()}
    >
      {loading ? 'Starting node… first launch can take up to a minute' : recentSessions.some((s) => s.saved.joinCode === joinCode) ? 'Resume Session' : 'Start Session'}
    </button>
  </div>
</main>
