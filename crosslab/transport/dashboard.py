"""
Embedded Real-Time HTML5/JS Dashboard for CrossLab.
Serves a zero-dependency reactive HUD at /dashboard showing live nodes, chat,
evidence graphs, and packet correlation timelines.
"""

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CrossLab: Multi-Machine Investigation HUD</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        body { background-color: #0b0f19; color: #e2e8f0; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }
        .glass-panel { background: rgba(17, 24, 39, 0.85); backdrop-filter: blur(12px); border: 1px solid rgba(55, 65, 81, 0.6); }
        .pulse-glow { box-shadow: 0 0 15px rgba(59, 130, 246, 0.5); }
    </style>
</head>
<body class="p-4 md:p-6 min-h-screen flex flex-col justify-between">
    <!-- Header -->
    <header class="flex flex-wrap justify-between items-center pb-4 mb-6 border-b border-gray-800">
        <div class="flex items-center space-x-3">
            <div class="w-4 h-4 rounded-full bg-emerald-500 animate-pulse"></div>
            <h1 class="text-2xl font-bold tracking-tight text-white flex items-center gap-2">
                <i class="fa-solid fa-network-wired text-blue-400"></i> CrossLab <span class="text-xs px-2 py-0.5 rounded bg-blue-900/60 text-blue-300 border border-blue-700">A2A v0.2.0</span>
            </h1>
        </div>
        <div class="flex items-center space-x-4 text-sm mt-2 md:mt-0">
            <span id="session-badge" class="px-3 py-1 rounded-full bg-gray-800 border border-gray-700 text-gray-300">Session: <strong class="text-white" id="session-id">loading...</strong></span>
            <span id="role-badge" class="px-3 py-1 rounded-full bg-purple-900/50 border border-purple-700 text-purple-200">Role: <strong id="agent-role">...</strong></span>
            <span id="agent-badge" class="px-3 py-1 rounded-full bg-blue-900/50 border border-blue-700 text-blue-200">Node: <strong id="agent-id">...</strong></span>
        </div>
    </header>

    <!-- Main Grid -->
    <main class="grid grid-cols-1 lg:grid-cols-3 gap-6 flex-grow">
        <!-- Col 1: Peers & Natural Language Stream -->
        <section class="flex flex-col space-y-6">
            <!-- Connected Nodes -->
            <div class="glass-panel rounded-xl p-4">
                <h2 class="text-sm font-semibold uppercase tracking-wider text-gray-400 mb-3 flex items-center gap-2">
                    <i class="fa-solid fa-server text-indigo-400"></i> Discovered Peer Nodes
                </h2>
                <div id="peers-list" class="space-y-2">
                    <div class="text-xs text-gray-500 italic">Listening for A2A peers...</div>
                </div>
            </div>

            <!-- Live A2A Chat Feed -->
            <div class="glass-panel rounded-xl p-4 flex flex-col flex-grow min-h-[350px]">
                <h2 class="text-sm font-semibold uppercase tracking-wider text-gray-400 mb-3 flex items-center justify-between">
                    <span class="flex items-center gap-2"><i class="fa-regular fa-comments text-cyan-400"></i> A2A Agent Dialogue</span>
                    <span class="text-xs text-emerald-400" id="live-indicator"><i class="fa-solid fa-circle text-[8px] animate-ping mr-1"></i>LIVE</span>
                </h2>
                <div id="chat-messages" class="flex-grow space-y-3 overflow-y-auto max-h-[380px] pr-2 text-xs">
                    <!-- Dynamic chat items -->
                </div>
                <div class="mt-3 pt-3 border-t border-gray-800 flex gap-2">
                    <input id="chat-input" type="text" placeholder="Send reasoning to peer agents..." class="flex-grow bg-gray-900 border border-gray-700 rounded px-3 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500">
                    <button id="chat-send-btn" class="bg-blue-600 hover:bg-blue-500 text-white px-3 py-1.5 rounded text-xs transition"><i class="fa-solid fa-paper-plane"></i></button>
                </div>
            </div>
        </section>

        <!-- Col 2: Evidence Graph & Hypotheses -->
        <section class="glass-panel rounded-xl p-4 flex flex-col">
            <h2 class="text-sm font-semibold uppercase tracking-wider text-gray-400 mb-3 flex items-center gap-2">
                <i class="fa-solid fa-diagram-project text-amber-400"></i> Hypotheses & Evidence Graph
            </h2>
            <div id="hypotheses-container" class="space-y-4 overflow-y-auto max-h-[700px] pr-2">
                <div class="text-xs text-gray-500 italic">No hypotheses proposed yet.</div>
            </div>
        </section>

        <!-- Col 3: Synchronized Runs & Time Correlation -->
        <section class="glass-panel rounded-xl p-4 flex flex-col space-y-4">
            <h2 class="text-sm font-semibold uppercase tracking-wider text-gray-400 mb-1 flex items-center gap-2">
                <i class="fa-solid fa-stopwatch text-rose-400"></i> Multi-Machine Run Correlation
            </h2>
            <div id="runs-container" class="space-y-4 overflow-y-auto max-h-[700px] pr-2">
                <div class="text-xs text-gray-500 italic">No synchronized test runs recorded yet.</div>
            </div>
        </section>
    </main>

    <!-- Footer -->
    <footer class="mt-6 pt-3 border-t border-gray-800 text-center text-xs text-gray-500 flex justify-between">
        <span>CrossLab Protocol: Zero-Implicit-Trust Collaboration</span>
        <a href="https://github.com/Ickleslimer/crosslab" target="_blank" class="hover:text-gray-300 transition flex items-center gap-1">
            <i class="fa-brands fa-github"></i> github.com/Ickleslimer/crosslab
        </a>
    </footer>

    <script>
        const baseUrl = window.location.origin;

        async function initDashboard() {
            try {
                // Fetch summary
                const res = await fetch(`${baseUrl}/v1/a2a/summary`);
                const summary = await res.json();
                document.getElementById('session-id').textContent = summary.session_id;

                const healthRes = await fetch(`${baseUrl}/health`);
                const health = await healthRes.json();
                document.getElementById('agent-id').textContent = health.agent_id;
                document.getElementById('agent-role').textContent = health.role;

                await refreshPeers();
                await refreshMessages();
                await refreshHypotheses();
                await refreshRuns();

                // Setup SSE
                setupSSE();
            } catch (err) {
                console.error("Initialization error:", err);
            }
        }

        async function refreshPeers() {
            const res = await fetch(`${baseUrl}/v1/a2a/peers`);
            const peers = await res.json();
            const container = document.getElementById('peers-list');
            if (!peers.length) {
                container.innerHTML = `<div class="text-xs text-gray-500 italic">No remote peers registered.</div>`;
                return;
            }
            container.innerHTML = peers.map(p => `
                <div class="p-2.5 rounded bg-gray-900/90 border border-gray-800 flex justify-between items-center text-xs">
                    <div>
                        <div class="font-bold text-white flex items-center gap-1.5">
                            <span class="w-2 h-2 rounded-full ${p.role === 'host' ? 'bg-blue-400' : 'bg-purple-400'}"></span>
                            ${p.agent_id}
                        </div>
                        <div class="text-gray-400 text-[11px]">${p.endpoint_url}</div>
                    </div>
                    <div class="text-right">
                        <span class="px-2 py-0.5 rounded text-[10px] uppercase font-semibold ${p.role === 'host' ? 'bg-blue-900/60 text-blue-300' : 'bg-purple-900/60 text-purple-300'}">${p.role}</span>
                        <div class="text-[10px] text-gray-500 mt-1">Offset: ${p.clock_offset_ms.toFixed(1)} ms</div>
                    </div>
                </div>
            `).join('');
        }

        async function refreshMessages() {
            const res = await fetch(`${baseUrl}/v1/a2a/messages`);
            const msgs = await res.json();
            const container = document.getElementById('chat-messages');
            if (!msgs.length) {
                container.innerHTML = `<div class="text-xs text-gray-500 italic">No messages yet.</div>`;
                return;
            }
            container.innerHTML = msgs.map(m => {
                const sid = m.sender_id.toLowerCase();
                let badgeLabel = m.sender_id;
                let badgeColor = 'bg-gray-800 text-gray-300 border-gray-700';

                if (sid.includes('human') || sid.includes('operator')) {
                    if (sid.includes('host')) {
                        badgeLabel = '👤 Human (Host)';
                        badgeColor = 'bg-emerald-900/60 text-emerald-300 border-emerald-600';
                    } else if (sid.includes('client')) {
                        badgeLabel = '👤 Human (Client)';
                        badgeColor = 'bg-amber-900/60 text-amber-300 border-amber-600';
                    } else {
                        badgeLabel = '👤 Human Operator';
                        badgeColor = 'bg-emerald-900/60 text-emerald-300 border-emerald-600';
                    }
                } else if (sid.includes('host')) {
                    badgeLabel = '🤖 Agent A (Host)';
                    badgeColor = 'bg-blue-900/50 text-blue-300 border-blue-700';
                } else if (sid.includes('client')) {
                    badgeLabel = '🤖 Agent B (Client)';
                    badgeColor = 'bg-purple-900/50 text-purple-300 border-purple-700';
                }

                return `
                    <div class="p-2.5 rounded bg-gray-900/80 border border-gray-800 space-y-1">
                        <div class="flex justify-between items-center text-[10px] text-gray-400">
                            <span class="font-semibold px-1.5 py-0.5 rounded border ${badgeColor}">${badgeLabel}</span>
                            <span>${m.timestamp ? m.timestamp.split('T')[1]?.slice(0, 8) : ''}</span>
                        </div>
                        <div class="text-gray-200 mt-1">${m.natural_language || JSON.stringify(m.payload)}</div>
                    </div>
                `;
            }).join('');
            container.scrollTop = container.scrollHeight;
        }

        async function refreshHypotheses() {
            const res = await fetch(`${baseUrl}/v1/a2a/hypotheses`);
            const hyps = await res.json();
            const container = document.getElementById('hypotheses-container');
            if (!hyps.length) {
                container.innerHTML = `<div class="text-xs text-gray-500 italic">No hypotheses proposed yet.</div>`;
                return;
            }
            container.innerHTML = hyps.map(h => {
                const statusColor = h.status === 'supported' ? 'bg-emerald-900/60 text-emerald-300 border-emerald-700' :
                                    h.status === 'contradicted' ? 'bg-rose-900/60 text-rose-300 border-rose-700' :
                                    'bg-amber-900/60 text-amber-300 border-amber-700';
                const evidenceList = (h.evidence_graph || []).map(ev => `
                    <li class="flex items-start gap-1.5 text-[11px] mt-1 text-gray-300">
                        <i class="fa-solid ${ev.relation === 'supports' ? 'fa-check text-emerald-400' : 'fa-xmark text-rose-400'} mt-0.5"></i>
                        <span>[${ev.evidence_type.toUpperCase()}] ${ev.rationale}</span>
                    </li>
                `).join('');

                return `
                    <div class="p-3 rounded-lg bg-gray-900 border border-gray-800 space-y-2">
                        <div class="flex justify-between items-start">
                            <div class="font-bold text-white text-xs">${h.title}</div>
                            <span class="px-2 py-0.5 rounded text-[10px] font-semibold border ${statusColor} uppercase">${h.status}</span>
                        </div>
                        <p class="text-xs text-gray-400">${h.description}</p>
                        ${h.evidence_graph && h.evidence_graph.length ? `
                            <div class="pt-2 border-t border-gray-800">
                                <div class="text-[10px] uppercase font-bold text-gray-500">Evidence Graph (${h.evidence_graph.length})</div>
                                <ul class="list-none pl-0 mt-1">${evidenceList}</ul>
                            </div>
                        ` : ''}
                    </div>
                `;
            }).join('');
        }

        async function refreshRuns() {
            const res = await fetch(`${baseUrl}/v1/a2a/runs`);
            const runs = await res.json();
            const container = document.getElementById('runs-container');
            if (!runs.length) {
                container.innerHTML = `<div class="text-xs text-gray-500 italic">No synchronized runs recorded yet.</div>`;
                return;
            }
            container.innerHTML = runs.map(r => {
                const corr = r.correlated_findings || {};
                const discrepancies = corr.discrepancies || [];
                return `
                    <div class="p-3 rounded-lg bg-gray-900 border border-gray-800 space-y-2">
                        <div class="flex justify-between items-center text-xs">
                            <span class="font-bold text-blue-400">Run #${r.run_id} (${r.build})</span>
                            <span class="px-2 py-0.5 rounded text-[10px] uppercase font-semibold ${r.outcome === 'reproduced' ? 'bg-rose-900/60 text-rose-300 border border-rose-700' : 'bg-gray-800 text-gray-300'}">${r.outcome}</span>
                        </div>
                        <div class="text-[11px] text-gray-400 flex justify-between">
                            <span>Host Pkts: <strong>${r.host?.last_received_packet ?? 'N/A'}</strong></span>
                            <span>Client Pkts: <strong>${r.client?.last_sent_packet ?? 'N/A'}</strong></span>
                        </div>
                        ${discrepancies.length ? `
                            <div class="pt-2 border-t border-gray-800 space-y-1">
                                <div class="text-[10px] uppercase font-bold text-amber-400">Discrepancies Detected (${discrepancies.length})</div>
                                ${discrepancies.map(d => `
                                    <div class="text-[11px] text-gray-300 bg-gray-950 p-2 rounded border border-gray-800">
                                        <div class="font-semibold text-yellow-300 text-[10px]">${d.code}</div>
                                        <div>${d.description}</div>
                                    </div>
                                `).join('')}
                            </div>
                        ` : ''}
                    </div>
                `;
            }).join('');
        }

        function setupSSE() {
            const evtSource = new EventSource(`${baseUrl}/v1/a2a/events`);
            evtSource.onmessage = function(event) {
                try {
                    const data = JSON.parse(event.data);
                    if (data.event === 'message') {
                        refreshMessages();
                        if (data.envelope && (data.envelope.action === 'start_run' || data.envelope.action === 'abort_run' || data.envelope.action === 'observation' || data.envelope.action === 'hypothesis')) {
                            refreshRuns();
                            refreshHypotheses();
                        }
                    } else if (data.event === 'peer_joined') {
                        refreshPeers();
                    } else if (data.event === 'hypothesis_proposed' || data.event === 'evidence_added') {
                        refreshHypotheses();
                    } else if (data.event === 'run_recorded' || data.event === 'sync_signal' || data.event === 'observation_added') {
                        refreshRuns();
                    }
                } catch(e) {}
            };

            // Periodic auto-refresh intervals for live HUD updates
            setInterval(refreshRuns, 3000);
            setInterval(refreshMessages, 2000);
            setInterval(refreshHypotheses, 5000);
            setInterval(refreshPeers, 8000);
        }

        // Chat send button
        document.getElementById('chat-send-btn').addEventListener('click', async () => {
            const input = document.getElementById('chat-input');
            const text = input.value.trim();
            if (!text) return;
            input.value = '';
            const role = document.getElementById('agent-role').textContent || 'host';
            await fetch(`${baseUrl}/v1/a2a/messages`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    sender_id: `human-${role}`,
                    action: 'chat',
                    natural_language: text,
                    relay: true
                })
            });
            refreshMessages();
        });

        document.getElementById('chat-input').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') document.getElementById('chat-send-btn').click();
        });

        window.onload = initDashboard;
    </script>
</body>
</html>
"""
