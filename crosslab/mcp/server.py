"""
Model Context Protocol (MCP) Server for CrossLab.
Exposes investigation tools to AI coding agents (Antigravity, Claude Code, Cursor, Gemini).
"""

import asyncio
import json
import sys
from typing import Any, Dict, List, Optional

from crosslab.agent.client import CrossLabClient
from crosslab.engine.session import InvestigationSession
from crosslab.protocol.actions import AgentRole, RunOutcome
from crosslab.protocol.models import RunRecord


class CrossLabMCPServer:
    """
    MCP Server providing tool execution over standard IO or in-process.
    """

    def __init__(self, session_or_client: Any = None):
        if isinstance(session_or_client, InvestigationSession):
            self.session = session_or_client
            self.client = None
        elif isinstance(session_or_client, CrossLabClient):
            self.client = session_or_client
            self.session = None
        else:
            # Default to in-process memory session
            self.session = InvestigationSession(session_id="default")
            self.client = None

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "crosslab_propose_hypothesis",
                "description": "Propose a new empirical hypothesis regarding the distributed bug.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Short title of the hypothesis"},
                        "description": {"type": "string", "description": "Detailed explanation and mechanism"},
                        "creator": {"type": "string", "description": "Name or role of agent proposing it"},
                        "confidence": {"type": "number", "description": "Initial confidence 0.0 to 1.0", "default": 0.5},
                    },
                    "required": ["title", "description", "creator"],
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
                "description": "Share a patch or diff file with the collaborating agent.",
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
        ]

    def execute_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        session = self.session
        if not session:
            return {"error": "In-process session not initialized"}

        if name == "crosslab_propose_hypothesis":
            hyp = session.propose_hypothesis(
                title=arguments["title"],
                description=arguments["description"],
                creator=arguments["creator"],
                confidence=arguments.get("confidence", 0.5),
            )
            return {"status": "ok", "hypothesis": hyp.model_dump()}

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
            qtype = arguments["query_type"]
            if qtype == "summary":
                return session.get_session_summary()
            elif qtype == "unresolved_hypotheses":
                hyps = session.get_unresolved_hypotheses()
                return {"unresolved_hypotheses": [h.model_dump() for h in hyps]}
            elif qtype == "latest_reproduced":
                run = session.get_latest_reproducing_run()
                return {"latest_reproduced_run": run.model_dump() if run else None}
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

        return {"error": f"Tool '{name}' not found"}

    def handle_json_rpc(self, request_str: str) -> str:
        try:
            req = json.loads(request_str)
            method = req.get("method")
            msg_id = req.get("id")

            if method == "tools/list":
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
    if "--test" in sys.argv:
        server = CrossLabMCPServer()
        tools = server.get_tool_definitions()
        print(f"[CrossLab MCP Server] Initialized with {len(tools)} tools:")
        for t in tools:
            print(f"  - {t['name']}: {t['description']}")
        return

    server = CrossLabMCPServer()
    for line in sys.stdin:
        if not line.strip():
            continue
        response = server.handle_json_rpc(line.strip())
        print(response, flush=True)


if __name__ == "__main__":
    main()
