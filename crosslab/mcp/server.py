"""
Model Context Protocol (MCP) Server for CrossLab.
Exposes investigation tools to AI coding agents and bridges requests to live A2A nodes.
"""

import argparse
import asyncio
import json
import os
import sys
from typing import Any, Dict, List, Optional
import httpx

from crosslab.agent.client import CrossLabClient
from crosslab.engine.session import InvestigationSession
from crosslab.protocol.actions import AgentRole, EvidenceRelation, EvidenceType, RunOutcome
from crosslab.protocol.models import RunRecord


class CrossLabMCPServer:
    """
    MCP Server providing tool execution over stdio or in-process.
    Bridges agent tool calls to the local A2A Node, which relays them across the network.
    """

    def __init__(self, node_url: Optional[str] = None, agent_id: str = "agent-mcp"):
        self.agent_id = agent_id
        env_url = os.environ.get("CROSSLAB_NODE_URL")
        target_url = node_url or env_url

        if target_url:
            self.client: Optional[CrossLabClient] = CrossLabClient(base_url=target_url, agent_id=agent_id)
            self.session: Optional[InvestigationSession] = None
        else:
            self.client = None
            self.session = InvestigationSession(session_id="default")

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "crosslab_send_chat",
                "description": "Send a natural language message or reasoning update to peer agents across the network.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "message": {"type": "string", "description": "Natural language text message"},
                        "recipient_id": {"type": "string", "description": "Optional specific recipient agent ID"},
                    },
                    "required": ["message"],
                },
            },
            {
                "name": "crosslab_propose_hypothesis",
                "description": "Propose an empirical hypothesis regarding the bug and broadcast it to peer agents.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Short title of the hypothesis"},
                        "description": {"type": "string", "description": "Detailed mechanism and reasoning"},
                        "parent_hypothesis_id": {"type": "string", "description": "Optional parent hypothesis ID if this is a refinement"},
                        "creator": {"type": "string", "description": "Agent proposing the hypothesis"},
                        "confidence": {"type": "number", "description": "Initial confidence 0.0 to 1.0", "default": 0.5},
                    },
                    "required": ["title", "description", "creator"],
                },
            },
            {
                "name": "crosslab_add_evidence",
                "description": "Attach an explicit supporting or contradicting evidence item to a hypothesis.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "hypothesis_id": {"type": "string", "description": "Hypothesis ID"},
                        "relation": {"type": "string", "enum": ["supports", "contradicts", "qualifies", "inconclusive"]},
                        "evidence_type": {"type": "string", "enum": ["run", "observation", "log", "counter_hypothesis"]},
                        "source_id": {"type": "string", "description": "Identifier of source (e.g. run ID '14')"},
                        "rationale": {"type": "string", "description": "Why this evidence supports or contradicts the hypothesis"},
                    },
                    "required": ["hypothesis_id", "relation", "rationale"],
                },
            },
            {
                "name": "crosslab_assess_hypothesis",
                "description": "Record an agent's confidence assessment on a hypothesis with reasoning.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "hypothesis_id": {"type": "string", "description": "Hypothesis ID"},
                        "confidence_score": {"type": "number", "description": "Subjective confidence score (0.0 to 1.0)"},
                        "rationale": {"type": "string", "description": "Reasoning for the confidence rating"},
                    },
                    "required": ["hypothesis_id", "confidence_score", "rationale"],
                },
            },
            {
                "name": "crosslab_challenge_hypothesis",
                "description": "Challenge an existing hypothesis with contradicting evidence or reasoning.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "hypothesis_id": {"type": "string", "description": "ID of hypothesis to challenge"},
                        "challenger": {"type": "string", "description": "Name or role of challenging agent"},
                        "reason": {"type": "string", "description": "Counter-reasoning"},
                        "counter_evidence": {"type": "string", "description": "Specific contradicting data or run ID"},
                    },
                    "required": ["hypothesis_id", "challenger", "reason"],
                },
            },
            {
                "name": "crosslab_propose_experiment",
                "description": "Propose a synchronized multi-machine test experiment (defining host and client roles).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "run_id": {"type": "integer", "description": "Sequential run ID"},
                        "title": {"type": "string", "description": "Experiment title"},
                        "rationale": {"type": "string", "description": "Why this experiment is proposed"},
                        "host_role": {"type": "string", "description": "Action host agent will execute locally"},
                        "client_role": {"type": "string", "description": "Action client agent will execute locally"},
                        "creator": {"type": "string", "description": "Agent proposing the experiment"},
                        "hypothesis_id": {"type": "string", "description": "Optional hypothesis being tested"},
                        "parameters": {"type": "object", "description": "Experiment parameters or timeouts"},
                    },
                    "required": ["run_id", "title", "rationale", "host_role", "client_role", "creator"],
                },
            },
            {
                "name": "crosslab_record_run",
                "description": "Record telemetry, packet logs, and disconnect results for a test run.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "run_id": {"type": "integer", "description": "Run ID"},
                        "hypothesis_id": {"type": "string", "description": "Hypothesis ID being tested"},
                        "build": {"type": "string", "description": "Build version string", "default": "netprobe-0.2.1"},
                        "participants": {"type": "array", "items": {"type": "string"}},
                        "outcome": {"type": "string", "enum": ["reproduced", "not_reproduced", "timeout", "success"]},
                        "host": {"type": "object", "description": "Host machine telemetry (disconnect_time, last_received_packet, reason, etc.)"},
                        "client": {"type": "object", "description": "Client machine telemetry (last_sent_packet, transport_result, displayed_reason, etc.)"},
                        "logs": {"type": "array", "items": {"type": "object"}},
                    },
                    "required": ["run_id", "host", "client"],
                },
            },
            {
                "name": "crosslab_correlate_run",
                "description": "Run cross-machine correlation on a run record to find packet drops, timing deltas, and anomalies.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "run_id": {"type": "integer", "description": "Run ID to correlate"},
                    },
                    "required": ["run_id"],
                },
            },
            {
                "name": "crosslab_query_investigation",
                "description": "Query shared investigation state: unresolved hypotheses, latest reproduced bug, run diffs, or summary.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query_type": {
                            "type": "string",
                            "enum": ["summary", "unresolved_hypotheses", "latest_reproduced", "diff_runs", "hypotheses", "experiments", "runs"],
                        },
                        "run_id_a": {"type": "integer", "description": "For diff_runs: first run ID"},
                        "run_id_b": {"type": "integer", "description": "For diff_runs: second run ID"},
                    },
                    "required": ["query_type"],
                },
            },
            {
                "name": "crosslab_share_patch",
                "description": "Share a patch or diff file with the collaborating agent across the network.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "filename": {"type": "string", "description": "Name of patch file e.g. fix_keepalive.patch"},
                        "patch_content": {"type": "string", "description": "Unified diff / patch text"},
                        "author_id": {"type": "string", "description": "Authoring agent ID"},
                        "description": {"type": "string", "description": "Explanation of the fix"},
                    },
                    "required": ["filename", "patch_content", "author_id", "description"],
                },
            },
            {
                "name": "crosslab_get_transcript",
                "description": "Fetch the full human-readable Markdown transcript of the investigation session.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "crosslab_wait_for_message",
                "description": (
                    "Block until an inbound peer A2A message arrives (replaces manual poll timers). "
                    "Returns the matching message envelope or {status: timeout}."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "since_id": {"type": "string", "description": "Return only messages after this message_id"},
                        "timeout_s": {"type": "number", "description": "Max seconds to wait", "default": 60},
                        "actions": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional action type filter e.g. ['chat', 'sync_ready']",
                        },
                        "exclude_self": {
                            "type": "boolean",
                            "description": "Exclude messages from this agent",
                            "default": True,
                        },
                    },
                },
            },
            {
                "name": "crosslab_get_run_state",
                "description": (
                    "Get barrier coordination state for a synchronized test run. "
                    "Returns phase (idle|paused|preparing|ready_wait|ready|running|completed|aborted), "
                    "ready flags per role, start_authorized, pause_reason, and instrumentation metadata."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "run_id": {"type": "integer", "description": "Run ID to query"},
                    },
                    "required": ["run_id"],
                },
            },
            {
                "name": "crosslab_send_sync_signal",
                "description": "Send a structured run sync signal (ready, start, abort, etc.) instead of prose CHAT.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "run_id": {"type": "integer"},
                        "phase": {"type": "string", "description": "e.g. ready, start, abort, prepare"},
                        "payload": {"type": "object", "description": "Optional metadata e.g. pid"},
                    },
                    "required": ["run_id", "phase"],
                },
            },
        ]

    async def execute_tool_async(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        if self.client:
            return await self._execute_tool_via_client(name, arguments)
        elif self.session:
            return self._execute_tool_in_process(name, arguments)
        return {"error": "Neither node client nor session initialized"}

    def execute_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Synchronous wrapper for MCP JSON-RPC handling."""
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        if loop.is_running():
            # Already in loop: run in executor or direct task
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, self.execute_tool_async(name, arguments))
                return future.result()
        else:
            return loop.run_until_complete(self.execute_tool_async(name, arguments))

    async def _execute_tool_via_client(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        client = self.client
        assert client is not None

        if name == "crosslab_send_chat":
            return await client.send_chat(text=arguments["message"], recipient_id=arguments.get("recipient_id"))

        elif name == "crosslab_propose_hypothesis":
            hyp = await client.propose_hypothesis(
                title=arguments["title"],
                description=arguments["description"],
                parent_hypothesis_id=arguments.get("parent_hypothesis_id"),
                confidence=arguments.get("confidence", 0.5),
            )
            return {"status": "ok", "hypothesis": hyp.model_dump()}

        elif name == "crosslab_add_evidence":
            ev = await client.add_evidence(
                hypothesis_id=arguments["hypothesis_id"],
                evidence_type=EvidenceType(arguments.get("evidence_type", "run")),
                relation=EvidenceRelation(arguments["relation"]),
                source_id=arguments.get("source_id", "agent"),
                rationale=arguments["rationale"],
            )
            return {"status": "ok", "evidence": ev.model_dump()}

        elif name == "crosslab_assess_hypothesis":
            return await client.assess_hypothesis(
                hypothesis_id=arguments["hypothesis_id"],
                confidence_score=arguments["confidence_score"],
                rationale=arguments["rationale"],
            )

        elif name == "crosslab_challenge_hypothesis":
            return await client.challenge_hypothesis(
                hypothesis_id=arguments["hypothesis_id"],
                reason=arguments["reason"],
                counter_evidence=arguments.get("counter_evidence"),
            )

        elif name == "crosslab_propose_experiment":
            exp = await client.propose_experiment(
                run_id=arguments["run_id"],
                title=arguments["title"],
                rationale=arguments["rationale"],
                host_role=arguments["host_role"],
                client_role=arguments["client_role"],
                hypothesis_id=arguments.get("hypothesis_id"),
                parameters=arguments.get("parameters"),
            )
            return {"status": "ok", "experiment": exp.model_dump()}

        elif name == "crosslab_record_run":
            outcome_val = arguments.get("outcome", "reproduced")
            outcome = RunOutcome(outcome_val) if outcome_val in [e.value for e in RunOutcome] else RunOutcome.REPRODUCED
            run = RunRecord(
                run_id=arguments["run_id"],
                hypothesis_id=arguments.get("hypothesis_id"),
                build=arguments.get("build", "default"),
                participants=arguments.get("participants", []),
                outcome=outcome,
                host=arguments.get("host", {}),
                client=arguments.get("client", {}),
                logs=arguments.get("logs", []),
            )
            return await client.submit_run_record(run)

        elif name == "crosslab_correlate_run":
            corr = await client.get_correlate(arguments["run_id"])
            return {"status": "ok", "correlation": corr.model_dump()}

        elif name == "crosslab_query_investigation":
            summary = await client.get_summary()
            qtype = arguments["query_type"]
            if qtype == "summary":
                return summary
            elif qtype == "unresolved_hypotheses":
                return {"unresolved_hypotheses": summary.get("unresolved_hypotheses", [])}
            elif qtype == "latest_reproduced":
                return {"latest_reproduced_run_id": summary.get("latest_reproduced_run_id")}
            return summary

        elif name == "crosslab_share_patch":
            art = await client.share_patch(
                filename=arguments["filename"],
                patch_content=arguments["patch_content"],
                description=arguments["description"],
            )
            return {"status": "ok", "artifact": art.model_dump()}

        elif name == "crosslab_get_transcript":
            text = await client.get_transcript()
            return {"status": "ok", "transcript": text}

        elif name == "crosslab_wait_for_message":
            return await client.wait_for_message(
                since_id=arguments.get("since_id"),
                timeout_s=arguments.get("timeout_s", 60.0),
                actions=arguments.get("actions"),
                exclude_self=arguments.get("exclude_self", True),
            )

        elif name == "crosslab_get_run_state":
            state = await client.get_barrier_state(arguments["run_id"])
            return {"status": "ok", "barrier": state}

        elif name == "crosslab_send_sync_signal":
            return await client.send_sync_signal(
                run_id=arguments["run_id"],
                phase=arguments["phase"],
                payload=arguments.get("payload"),
            )

        return {"error": f"Tool '{name}' not found"}

    def _execute_tool_in_process(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        session = self.session
        assert session is not None

        if name == "crosslab_propose_hypothesis":
            hyp = session.propose_hypothesis(
                title=arguments["title"],
                description=arguments["description"],
                creator=arguments["creator"],
                parent_hypothesis_id=arguments.get("parent_hypothesis_id"),
                confidence=arguments.get("confidence", 0.5),
            )
            return {"status": "ok", "hypothesis": hyp.model_dump()}

        elif name == "crosslab_add_evidence":
            ev = session.add_evidence(
                hypothesis_id=arguments["hypothesis_id"],
                evidence_type=EvidenceType(arguments.get("evidence_type", "run")),
                relation=EvidenceRelation(arguments["relation"]),
                source_agent_id=arguments.get("source_agent_id", "mcp-agent"),
                source_id=arguments.get("source_id", "agent"),
                rationale=arguments["rationale"],
            )
            return {"status": "ok", "evidence": ev.model_dump() if ev else None}

        elif name == "crosslab_assess_hypothesis":
            ass = session.assess_hypothesis(
                hypothesis_id=arguments["hypothesis_id"],
                agent_id=arguments.get("agent_id", "mcp-agent"),
                confidence_score=arguments["confidence_score"],
                rationale=arguments["rationale"],
            )
            return {"status": "ok", "assessment": ass.model_dump() if ass else None}

        elif name == "crosslab_challenge_hypothesis":
            hyp = session.challenge_hypothesis(
                hypothesis_id=arguments["hypothesis_id"],
                challenger=arguments["challenger"],
                reason=arguments["reason"],
                counter_evidence=arguments.get("counter_evidence"),
            )
            if not hyp:
                return {"error": f"Hypothesis {arguments['hypothesis_id']} not found"}
            return {"status": "ok", "hypothesis": hyp.model_dump()}

        elif name == "crosslab_propose_experiment":
            exp = session.propose_experiment(
                run_id=arguments["run_id"],
                title=arguments["title"],
                rationale=arguments["rationale"],
                host_role=arguments["host_role"],
                client_role=arguments["client_role"],
                creator=arguments["creator"],
                hypothesis_id=arguments.get("hypothesis_id"),
                parameters=arguments.get("parameters"),
            )
            return {"status": "ok", "experiment": exp.model_dump()}

        elif name == "crosslab_record_run":
            outcome_val = arguments.get("outcome", "reproduced")
            outcome = RunOutcome(outcome_val) if outcome_val in [e.value for e in RunOutcome] else RunOutcome.REPRODUCED
            run = RunRecord(
                run_id=arguments["run_id"],
                hypothesis_id=arguments.get("hypothesis_id"),
                build=arguments.get("build", "default"),
                participants=arguments.get("participants", []),
                outcome=outcome,
                host=arguments.get("host", {}),
                client=arguments.get("client", {}),
                logs=arguments.get("logs", []),
            )
            saved = session.record_run(run)
            return {"status": "ok", "run": saved.model_dump()}

        elif name == "crosslab_correlate_run":
            run = session.get_run(arguments["run_id"])
            if not run:
                return {"error": f"Run {arguments['run_id']} not found"}
            corr = session.correlator.correlate_run(run)
            return {"status": "ok", "correlation": corr.model_dump()}

        elif name == "crosslab_query_investigation":
            qtype = arguments.get("query_type") or arguments.get("query") or "summary"
            if qtype == "summary":
                return session.get_session_summary()
            elif qtype == "unresolved_hypotheses":
                hyps = session.get_unresolved_hypotheses()
                return {"unresolved_hypotheses": [h.model_dump() for h in hyps]}
            elif qtype == "latest_reproduced":
                run = session.get_latest_reproducing_run()
                return {"latest_reproduced_run": run.model_dump() if run else None}
            elif qtype == "latest_run":
                runs = session.get_runs()
                return {"latest_run": runs[-1].model_dump() if runs else None}
            elif qtype == "diff_runs":
                ra = arguments.get("run_id_a")
                rb = arguments.get("run_id_b")
                if ra is None or rb is None:
                    return {"error": "Must supply run_id_a and run_id_b"}
                diff = session.diff_runs(ra, rb)
                return {"diff": diff}
            elif qtype == "hypotheses":
                return {"hypotheses": [h.model_dump() for h in session.get_hypotheses()]}
            elif qtype == "experiments":
                return {"experiments": [e.model_dump() for e in session.get_experiments()]}
            elif qtype == "runs":
                return {"runs": [r.model_dump() for r in session.get_runs()]}
            else:
                return {"error": f"Unknown query type: {qtype}"}

        elif name == "crosslab_share_patch":
            art = session.share_artifact(
                filename=arguments["filename"],
                content_type="text/x-patch",
                content=arguments["patch_content"],
                author_id=arguments["author_id"],
                description=arguments["description"],
            )
            return {"status": "ok", "artifact": art.model_dump()}

        elif name == "crosslab_get_transcript":
            text = session.export_transcript_markdown()
            return {"status": "ok", "transcript": text}

        return {"error": f"Tool '{name}' not found"}

    def handle_json_rpc(self, request_str: str) -> Optional[str]:
        try:
            req = json.loads(request_str)
            method = req.get("method")
            msg_id = req.get("id")

            if method == "initialize":
                return json.dumps({
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {
                            "tools": {
                                "listChanged": False
                            },
                            "resources": {
                                "subscribe": False,
                                "listChanged": False
                            },
                            "prompts": {
                                "listChanged": False
                            }
                        },
                        "serverInfo": {
                            "name": "crosslab-mcp-server",
                            "version": "0.3.0"
                        }
                    }
                })
            elif method in ("notifications/initialized", "initialized"):
                # Standard MCP notification confirming client initialization
                return None
            elif method == "ping":
                return json.dumps({
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {}
                })
            elif method == "resources/list":
                return json.dumps({
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "resources": [
                            {
                                "uri": "crosslab://investigation/summary",
                                "name": "Investigation Summary",
                                "description": "High-level summary of active investigation session, peers, hypotheses, and runs.",
                                "mimeType": "application/json"
                            },
                            {
                                "uri": "crosslab://hypotheses/active",
                                "name": "Active Hypotheses",
                                "description": "Current empirical hypotheses and their evidence graphs.",
                                "mimeType": "application/json"
                            },
                            {
                                "uri": "crosslab://runs/latest",
                                "name": "Latest Test Run",
                                "description": "Most recent synchronized multi-machine test run telemetry.",
                                "mimeType": "application/json"
                            },
                            {
                                "uri": "crosslab://ledger/messages",
                                "name": "A2A Message Ledger",
                                "description": "Recent Agent-to-Agent message log and reasoning records.",
                                "mimeType": "application/json"
                            }
                        ]
                    }
                })
            elif method == "resources/read":
                params = req.get("params", {})
                uri = params.get("uri", "")
                content_text = "{}"
                if uri == "crosslab://investigation/summary":
                    content_text = json.dumps(self.execute_tool("crosslab_query_investigation", {"query": "summary"}), indent=2)
                elif uri == "crosslab://hypotheses/active":
                    content_text = json.dumps(self.execute_tool("crosslab_query_investigation", {"query": "hypotheses"}), indent=2)
                elif uri == "crosslab://runs/latest":
                    content_text = json.dumps(self.execute_tool("crosslab_query_investigation", {"query": "latest_run"}), indent=2)
                elif uri == "crosslab://ledger/messages":
                    if self.client:
                        try:
                            res = self.client._get("/v1/a2a/messages?limit=20")
                            content_text = json.dumps(res, indent=2)
                        except Exception:
                            content_text = "[]"
                    else:
                        msgs = [m.model_dump() for m in self.local_session.get_messages(limit=20)]
                        content_text = json.dumps(msgs, indent=2)
                else:
                    return json.dumps({
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "error": {"code": -32602, "message": f"Unknown resource URI: {uri}"}
                    })

                return json.dumps({
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "contents": [
                            {
                                "uri": uri,
                                "mimeType": "application/json",
                                "text": content_text
                            }
                        ]
                    }
                })
            elif method == "prompts/list":
                return json.dumps({
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "prompts": [
                            {
                                "name": "investigate_fear3_host",
                                "description": "System guidelines for Host AI Agent debugging FEAR 3 co-op disconnects.",
                                "arguments": []
                            },
                            {
                                "name": "investigate_fear3_client",
                                "description": "System guidelines for Client AI Agent debugging FEAR 3 co-op disconnects.",
                                "arguments": []
                            }
                        ]
                    }
                })
            elif method == "prompts/get":
                params = req.get("params", {})
                prompt_name = params.get("name", "")
                if prompt_name == "investigate_fear3_host":
                    prompt_text = "You are Agent A (Host Investigator) running CrossLab. Trace host-side packet queues, watchdog timers, and coordinate synchronized test runs with Agent B."
                elif prompt_name == "investigate_fear3_client":
                    prompt_text = "You are Agent B (Client Investigator) running CrossLab. Trace client-side SendP2PPacket calls, monitor transport return codes, and coordinate with Agent A."
                else:
                    return json.dumps({
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "error": {"code": -32602, "message": f"Unknown prompt name: {prompt_name}"}
                    })

                return json.dumps({
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "description": f"Prompt for {prompt_name}",
                        "messages": [
                            {
                                "role": "user",
                                "content": {
                                    "type": "text",
                                    "text": prompt_text
                                }
                            }
                        ]
                    }
                })
            elif method == "tools/list":
                return json.dumps({
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {"tools": self.get_tool_definitions()},
                })
            elif method == "tools/call":
                params = req.get("params", {})
                tool_name = params.get("name")
                args = params.get("arguments", {})
                result = self.execute_tool(tool_name, args)
                return json.dumps({
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]},
                })
            else:
                if msg_id is None:
                    return None  # Notification
                return json.dumps({
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {"code": -32601, "message": f"Method '{method}' not found"},
                })
        except Exception as e:
            return json.dumps({
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": f"Parse error: {str(e)}"},
            })


def main() -> None:
    parser = argparse.ArgumentParser(description="CrossLab MCP Server")
    parser.add_argument("--node-url", type=str, default=None, help="Target CrossLab node URL e.g. http://127.0.0.1:8000")
    parser.add_argument("--test", action="store_true", help="Print tool definitions and exit")
    args = parser.parse_args()

    server = CrossLabMCPServer(node_url=args.node_url)

    if args.test:
        tools = server.get_tool_definitions()
        print(f"[CrossLab MCP Server] Initialized with {len(tools)} tools (Bridge target: {server.client.base_url if server.client else 'in-process'}):")
        for t in tools:
            print(f"  - {t['name']}: {t['description']}")
        return

    for line in sys.stdin:
        if not line.strip():
            continue
        response = server.handle_json_rpc(line.strip())
        if response is not None:
            print(response, flush=True)


if __name__ == "__main__":
    main()
