"""
Investigation Session Manager for CrossLab.
Coordinates hypotheses, experiments, runs, observations, and answers investigation queries.
"""

from typing import Any, Dict, List, Optional

from crosslab.engine.correlator import CorrelationEngine
from crosslab.engine.storage import Storage
from crosslab.protocol.actions import (
    ExperimentStatus,
    HypothesisStatus,
    RunOutcome,
)
from crosslab.protocol.models import (
    AgentPeer,
    ArtifactPayload,
    CorrelationResult,
    Experiment,
    Hypothesis,
    InstrumentationRequest,
    MessageEnvelope,
    Observation,
    RunRecord,
    utc_now_iso,
)


class InvestigationSession:
    def __init__(self, session_id: str = "default", db_path: str = ":memory:"):
        self.session_id = session_id
        self.storage = Storage(db_path)
        self.storage.ensure_session(session_id)
        self.correlator = CorrelationEngine()

    # --- Peers & Messages ---

    def register_peer(self, peer: AgentPeer) -> None:
        self.storage.upsert_peer(peer, session_id=self.session_id)

    def get_peers(self) -> List[AgentPeer]:
        return self.storage.get_peers(session_id=self.session_id)

    def record_message(self, msg: MessageEnvelope) -> None:
        msg.session_id = self.session_id
        self.storage.save_message(msg)

    def get_messages(self, limit: int = 100) -> List[MessageEnvelope]:
        return self.storage.get_messages(session_id=self.session_id, limit=limit)

    # --- Hypotheses Management ---

    def propose_hypothesis(
        self,
        title: str,
        description: str,
        creator: str,
        confidence: float = 0.5,
    ) -> Hypothesis:
        hyp = Hypothesis(
            session_id=self.session_id,
            title=title,
            description=description,
            creator=creator,
            status=HypothesisStatus.ACTIVE,
            confidence=confidence,
        )
        self.storage.save_hypothesis(hyp)
        return hyp

    def challenge_hypothesis(
        self,
        hypothesis_id: str,
        challenger: str,
        reason: str,
        counter_evidence: Optional[str] = None,
    ) -> Optional[Hypothesis]:
        hyp = self.storage.get_hypothesis(hypothesis_id)
        if not hyp:
            return None
        hyp.evidence_against.append(f"[{challenger}] {reason}")
        if counter_evidence:
            hyp.evidence_against.append(f"[{challenger} Evidence] {counter_evidence}")
        hyp.confidence = max(0.0, hyp.confidence - 0.2)
        hyp.status = HypothesisStatus.CONTRADICTED if hyp.confidence < 0.3 else HypothesisStatus.ACTIVE
        hyp.updated_at = utc_now_iso()
        self.storage.save_hypothesis(hyp)
        return hyp

    def update_hypothesis(
        self,
        hypothesis_id: str,
        status: Optional[HypothesisStatus] = None,
        confidence: Optional[float] = None,
        supporting_run_id: Optional[int] = None,
        contradicting_run_id: Optional[int] = None,
    ) -> Optional[Hypothesis]:
        hyp = self.storage.get_hypothesis(hypothesis_id)
        if not hyp:
            return None
        if status:
            hyp.status = status
        if confidence is not None:
            hyp.confidence = confidence
        if supporting_run_id and supporting_run_id not in hyp.supporting_run_ids:
            hyp.supporting_run_ids.append(supporting_run_id)
        if contradicting_run_id and contradicting_run_id not in hyp.contradicting_run_ids:
            hyp.contradicting_run_ids.append(contradicting_run_id)
        hyp.updated_at = utc_now_iso()
        self.storage.save_hypothesis(hyp)
        return hyp

    def get_hypotheses(self) -> List[Hypothesis]:
        return self.storage.get_hypotheses(session_id=self.session_id)

    def get_unresolved_hypotheses(self) -> List[Hypothesis]:
        """Which hypotheses remain unresolved?"""
        all_hyp = self.get_hypotheses()
        return [
            h for h in all_hyp
            if h.status in (HypothesisStatus.PROPOSED, HypothesisStatus.ACTIVE, HypothesisStatus.CONTRADICTED)
        ]

    # --- Experiments Management ---

    def propose_experiment(
        self,
        run_id: int,
        title: str,
        rationale: str,
        host_role: str,
        client_role: str,
        creator: str,
        hypothesis_id: Optional[str] = None,
        parameters: Optional[Dict[str, Any]] = None,
    ) -> Experiment:
        exp = Experiment(
            session_id=self.session_id,
            run_id=run_id,
            hypothesis_id=hypothesis_id,
            title=title,
            rationale=rationale,
            host_role=host_role,
            client_role=client_role,
            creator=creator,
            parameters=parameters or {},
            status=ExperimentStatus.PROPOSED,
        )
        self.storage.save_experiment(exp)
        return exp

    def accept_experiment(self, experiment_id: str) -> Optional[Experiment]:
        experiments = self.storage.get_experiments(session_id=self.session_id)
        for exp in experiments:
            if exp.id == experiment_id:
                exp.status = ExperimentStatus.ACCEPTED
                self.storage.save_experiment(exp)
                return exp
        return None

    def get_experiments(self) -> List[Experiment]:
        return self.storage.get_experiments(session_id=self.session_id)

    # --- Runs & Correlation ---

    def record_run(self, run: RunRecord) -> RunRecord:
        run.session_id = self.session_id
        
        # Attach hypothesis title if missing
        if run.hypothesis_id and not run.hypothesis_title:
            hyp = self.storage.get_hypothesis(run.hypothesis_id)
            if hyp:
                run.hypothesis_title = hyp.title

        # Run correlation analysis
        corr_res = self.correlator.correlate_run(run)
        run.correlated_findings = corr_res.model_dump()

        if corr_res.reproduced and run.outcome == RunOutcome.PENDING:
            run.outcome = RunOutcome.REPRODUCED

        self.storage.save_run(run)

        # Update hypothesis evidence if attached
        if run.hypothesis_id:
            if corr_res.reproduced and "SUPPORTED" in (corr_res.hypothesis_verdict or ""):
                self.update_hypothesis(
                    run.hypothesis_id,
                    status=HypothesisStatus.SUPPORTED,
                    confidence=0.85,
                    supporting_run_id=run.run_id,
                )
            elif not corr_res.reproduced and run.outcome == RunOutcome.NOT_REPRODUCED:
                self.update_hypothesis(
                    run.hypothesis_id,
                    status=HypothesisStatus.CONTRADICTED,
                    confidence=0.2,
                    contradicting_run_id=run.run_id,
                )

        return run

    def get_runs(self) -> List[RunRecord]:
        return self.storage.get_runs(session_id=self.session_id)

    def get_run(self, run_id: int) -> Optional[RunRecord]:
        return self.storage.get_run(run_id, session_id=self.session_id)

    def get_latest_reproducing_run(self) -> Optional[RunRecord]:
        """Which experiment last reproduced the bug?"""
        runs = self.get_runs()
        reproduced = [r for r in runs if r.outcome == RunOutcome.REPRODUCED]
        return reproduced[-1] if reproduced else None

    def diff_runs(self, run_id_a: int, run_id_b: int) -> Optional[Dict[str, Any]]:
        """What changed between Run A and Run B?"""
        run_a = self.get_run(run_id_a)
        run_b = self.get_run(run_id_b)
        if not run_a or not run_b:
            return None
        return self.correlator.diff_runs(run_a, run_b)

    # --- Observations, Instrumentation, Artifacts ---

    def add_observation(
        self,
        run_id: int,
        agent_id: str,
        metric_name: str,
        value: Any,
        unit: Optional[str] = None,
        tags: Optional[List[str]] = None,
        notes: Optional[str] = None,
    ) -> Observation:
        obs = Observation(
            session_id=self.session_id,
            run_id=run_id,
            agent_id=agent_id,
            metric_name=metric_name,
            value=value,
            unit=unit,
            tags=tags or [],
            notes=notes,
        )
        self.storage.save_observation(obs)
        return obs

    def get_observations(self, run_id: Optional[int] = None) -> List[Observation]:
        return self.storage.get_observations(session_id=self.session_id, run_id=run_id)

    def get_contradicting_observations(self, hypothesis_id: str) -> List[Observation]:
        """Which observations contradict our current theory?"""
        hyp = self.storage.get_hypothesis(hypothesis_id)
        if not hyp or not hyp.contradicting_run_ids:
            return []
        contradicting_obs = []
        for run_id in hyp.contradicting_run_ids:
            contradicting_obs.extend(self.get_observations(run_id=run_id))
        return contradicting_obs

    def request_instrumentation(
        self,
        requester_id: str,
        target_agent_id: str,
        target_module: str,
        trace_type: str,
        rationale: str,
        target_function: Optional[str] = None,
        parameters: Optional[Dict[str, Any]] = None,
        sampling_rate_ms: int = 100,
    ) -> InstrumentationRequest:
        req = InstrumentationRequest(
            session_id=self.session_id,
            requester_id=requester_id,
            target_agent_id=target_agent_id,
            target_module=target_module,
            target_function=target_function,
            trace_type=trace_type,
            parameters=parameters or {},
            sampling_rate_ms=sampling_rate_ms,
            rationale=rationale,
            status="pending",
        )
        self.storage.save_instrumentation_request(req)
        return req

    def get_instrumentation_requests(self) -> List[InstrumentationRequest]:
        return self.storage.get_instrumentation_requests(session_id=self.session_id)

    def share_artifact(
        self,
        filename: str,
        content_type: str,
        content: str,
        author_id: str,
        description: Optional[str] = None,
    ) -> ArtifactPayload:
        art = ArtifactPayload(
            session_id=self.session_id,
            filename=filename,
            content_type=content_type,
            content=content,
            author_id=author_id,
            description=description,
        )
        self.storage.save_artifact(art)
        return art

    def get_artifacts(self) -> List[ArtifactPayload]:
        return self.storage.get_artifacts(session_id=self.session_id)

    def get_session_summary(self) -> Dict[str, Any]:
        peers = self.get_peers()
        hypotheses = self.get_hypotheses()
        experiments = self.get_experiments()
        runs = self.get_runs()
        latest_reproduced = self.get_latest_reproducing_run()

        return {
            "session_id": self.session_id,
            "peers_count": len(peers),
            "peers": [p.model_dump() for p in peers],
            "total_hypotheses": len(hypotheses),
            "unresolved_hypotheses": [h.model_dump() for h in self.get_unresolved_hypotheses()],
            "total_experiments": len(experiments),
            "total_runs": len(runs),
            "latest_reproduced_run_id": latest_reproduced.run_id if latest_reproduced else None,
            "latest_run": runs[-1].model_dump() if runs else None,
        }
