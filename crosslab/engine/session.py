"""
Investigation Session Manager for CrossLab.
Coordinates hypotheses with explicit evidence graphs, experiments, runs, and distributed queries.
"""

import re
from typing import Any, Dict, List, Optional

from crosslab.engine.correlator import CorrelationEngine
from crosslab.engine.storage import Storage
from crosslab.protocol.actions import (
    ActionType,
    EvidenceRelation,
    EvidenceType,
    ExperimentStatus,
    HypothesisStatus,
    RunOutcome,
)
from crosslab.protocol.models import (
    AgentAssessment,
    AgentPeer,
    ArtifactPayload,
    CorrelationResult,
    EvidenceItem,
    Experiment,
    Hypothesis,
    InstrumentationRequest,
    MessageEnvelope,
    Observation,
    RunRecord,
    utc_now_iso,
)


class InvestigationSession:
    def __init__(
        self,
        session_id: str = "default",
        db_path: str = ":memory:",
        transcript_dir: Optional[str] = None,
        enable_transcript: Optional[bool] = None,
    ):
        self.session_id = session_id
        self.storage = Storage(
            db_path=db_path,
            transcript_dir=transcript_dir,
            enable_transcript=enable_transcript,
        )
        self.storage.ensure_session(session_id)
        self.correlator = CorrelationEngine()

    def get_transcript_path(self) -> Optional[str]:
        """Return the absolute path to the session's live Markdown transcript file."""
        recorder = self.storage.get_transcript_recorder(self.session_id)
        if recorder:
            return str(recorder.get_file_path())
        return None

    def close(self) -> None:
        """Close storage and underlying database connections."""
        if hasattr(self, "storage") and self.storage is not None:
            self.storage.close()

    def export_transcript_markdown(self, output_path: Optional[str] = None) -> str:
        """Generate and optionally save the full structured Markdown transcript."""
        recorder = self.storage.get_transcript_recorder(self.session_id)
        if not recorder:
            from crosslab.engine.transcript import TranscriptRecorder
            recorder = TranscriptRecorder(session_id=self.session_id)
        
        md_content = recorder.generate_full_markdown(self.storage)
        if output_path:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(md_content)
        return md_content

    # --- Peers & Messages ---

    def register_peer(self, peer: AgentPeer) -> None:
        self.storage.upsert_peer(peer, session_id=self.session_id)

    def get_peers(self) -> List[AgentPeer]:
        return self.storage.get_peers(session_id=self.session_id)

    def prune_remote_peers(self, keep_agent_id: str) -> None:
        self.storage.clear_remote_peers(self.session_id, keep_agent_id)

    def remove_peer(self, agent_id: str) -> None:
        self.storage.remove_peer(agent_id, session_id=self.session_id)

    def record_message(self, msg: MessageEnvelope) -> None:
        msg.session_id = self.session_id
        self.storage.save_message(msg)
        self._auto_sync_from_message(msg)

    def _auto_sync_from_message(self, msg: MessageEnvelope) -> None:
        """
        Hardening: Automatically synchronizes formal RunRecord, Hypothesis, and Evidence
        entities when message envelopes contain run coordination or empirical lifecycle signals.
        """
        try:
            text = msg.natural_language or ""
            payload = msg.payload or {}
            action = msg.action

            # Extract run_id if present
            run_id: Optional[int] = None
            if "run_id" in payload:
                try:
                    run_id = int(payload["run_id"])
                except (ValueError, TypeError):
                    pass
            if run_id is None and text:
                m = re.search(r"(?:START\s+RUN|RUN\s+IN\s+PROGRESS|ABORT\s+RUN|START\s+Run|Run\s*#?|run\s*#?)\s*(\d+)", text, re.IGNORECASE)
                if m:
                    try:
                        run_id = int(m.group(1))
                    except ValueError:
                        pass

            if run_id is not None:
                existing_run = self.get_run(run_id)
                if not existing_run:
                    existing_run = RunRecord(
                        run_id=run_id,
                        session_id=self.session_id,
                        build=payload.get("build", "default-build"),
                        start_time=msg.timestamp,
                        outcome=RunOutcome.PENDING,
                        participants=[msg.sender_id] if msg.sender_id else [],
                        created_at=msg.timestamp,
                    )
                else:
                    if msg.sender_id and msg.sender_id not in existing_run.participants:
                        existing_run.participants.append(msg.sender_id)

                # Action-specific updates
                if action in (ActionType.START_RUN, ActionType.SYNC_READY):
                    existing_run.start_time = existing_run.start_time or msg.timestamp
                    if existing_run.outcome == RunOutcome.PENDING:
                        existing_run.outcome = RunOutcome.PENDING
                    if "commit" in text.lower():
                        cm = re.search(r"commit\s+([0-9a-fA-F]+)", text, re.IGNORECASE)
                        if cm:
                            existing_run.build = f"commit-{cm.group(1)}"
                    if "exp_" in text:
                        em = re.search(r"(exp_[0-9a-fA-F]+)", text)
                        if em:
                            existing_run.experiment_id = em.group(1)
                    if "hyp_" in text:
                        hm = re.search(r"(hyp_[0-9a-fA-F]+)", text)
                        if hm:
                            existing_run.hypothesis_id = hm.group(1)

                elif action in (ActionType.ABORT_RUN, ActionType.REPORT_FAILURE):
                    existing_run.end_time = msg.timestamp
                    if any(k in text.lower() for k in ("crash", "bex", "exception", "fault")):
                        existing_run.outcome = RunOutcome.CRASH
                    else:
                        existing_run.outcome = RunOutcome.NOT_REPRODUCED
                    existing_run.result_summary = text

                elif action == ActionType.REPORT_RESULT:
                    existing_run.end_time = msg.timestamp
                    if "reproduced" in text.lower() or "reproduce" in text.lower():
                        existing_run.outcome = RunOutcome.REPRODUCED
                    elif "success" in text.lower() or "passed" in text.lower():
                        existing_run.outcome = RunOutcome.SUCCESS
                    existing_run.result_summary = text

                elif action == ActionType.CHAT:
                    if re.search(r"RUN\s+\d+\s+REPRODUCED", text, re.IGNORECASE):
                        existing_run.outcome = RunOutcome.REPRODUCED
                        existing_run.end_time = msg.timestamp
                        existing_run.result_summary = text
                    elif re.search(r"ABORT\s+RUN\s+\d+", text, re.IGNORECASE):
                        if "crash" in text.lower():
                            existing_run.outcome = RunOutcome.CRASH
                        else:
                            existing_run.outcome = RunOutcome.NOT_REPRODUCED
                        existing_run.end_time = msg.timestamp
                        existing_run.result_summary = text

                # Ensure observations are linked
                existing_obs = self.storage.get_observations(session_id=self.session_id, run_id=run_id)
                if existing_obs:
                    existing_run.observations = existing_obs

                self.record_run(existing_run)

            # Hypothesis auto-sync
            if action == ActionType.PROPOSE_HYPOTHESIS and payload:
                title = payload.get("title") or payload.get("hypothesis")
                if title and not self.storage.get_hypothesis(payload.get("id", "")):
                    self.propose_hypothesis(
                        title=str(title),
                        description=payload.get("description", text),
                        creator=msg.sender_id,
                        confidence=payload.get("confidence"),
                    )
        except Exception:
            pass

    def get_messages(self, limit: Optional[int] = 100) -> List[MessageEnvelope]:
        return self.storage.get_messages(session_id=self.session_id, limit=limit)

    # --- Hypotheses & Evidence Graph ---

    def propose_hypothesis(
        self,
        title: str,
        description: str,
        creator: str,
        parent_hypothesis_id: Optional[str] = None,
        confidence: Optional[float] = None,
    ) -> Hypothesis:
        hyp = Hypothesis(
            session_id=self.session_id,
            title=title,
            description=description,
            creator=creator,
            parent_hypothesis_id=parent_hypothesis_id,
            status=HypothesisStatus.ACTIVE,
            confidence=confidence,
        )
        if confidence is not None:
            hyp.agent_assessments[creator] = AgentAssessment(
                agent_id=creator,
                confidence_score=confidence,
                rationale="Initial author assessment",
            )
        self.storage.save_hypothesis(hyp)
        return hyp

    def add_evidence(
        self,
        hypothesis_id: str,
        evidence_type: EvidenceType,
        relation: EvidenceRelation,
        source_agent_id: str,
        source_id: str,
        rationale: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> Optional[EvidenceItem]:
        hyp = self.storage.get_hypothesis(hypothesis_id)
        if not hyp:
            return None
        ev = EvidenceItem(
            evidence_type=evidence_type,
            relation=relation,
            source_agent_id=source_agent_id,
            source_id=source_id,
            rationale=rationale,
            details=details or {},
        )
        hyp.evidence_graph.append(ev)
        
        # Update hypothesis state if evidence is conclusive
        supports = sum(1 for e in hyp.evidence_graph if e.relation == EvidenceRelation.SUPPORTS)
        contradicts = sum(1 for e in hyp.evidence_graph if e.relation == EvidenceRelation.CONTRADICTS)
        
        if contradicts > 0 and supports == 0:
            hyp.status = HypothesisStatus.CONTRADICTED
        elif supports > 0 and contradicts == 0:
            hyp.status = HypothesisStatus.SUPPORTED
        elif supports > 0 and contradicts > 0:
            hyp.status = HypothesisStatus.INCONCLUSIVE

        hyp.updated_at = utc_now_iso()
        self.storage.save_hypothesis(hyp)
        return ev

    def assess_hypothesis(
        self,
        hypothesis_id: str,
        agent_id: str,
        confidence_score: float,
        rationale: str,
    ) -> Optional[AgentAssessment]:
        hyp = self.storage.get_hypothesis(hypothesis_id)
        if not hyp:
            return None
        assessment = AgentAssessment(
            agent_id=agent_id,
            confidence_score=confidence_score,
            rationale=rationale,
        )
        hyp.agent_assessments[agent_id] = assessment
        # Update overall consensus confidence
        scores = [a.confidence_score for a in hyp.agent_assessments.values()]
        hyp.confidence = sum(scores) / len(scores) if scores else None
        hyp.updated_at = utc_now_iso()
        self.storage.save_hypothesis(hyp)
        return assessment

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
        
        self.add_evidence(
            hypothesis_id=hypothesis_id,
            evidence_type=EvidenceType.COUNTER_HYPOTHESIS,
            relation=EvidenceRelation.CONTRADICTS,
            source_agent_id=challenger,
            source_id=counter_evidence or "reasoning",
            rationale=reason,
        )
        # Update assessment for challenger
        self.assess_hypothesis(
            hypothesis_id=hypothesis_id,
            agent_id=challenger,
            confidence_score=0.2,
            rationale=f"Challenged: {reason}",
        )
        return self.storage.get_hypothesis(hypothesis_id)

    def get_hypotheses(self) -> List[Hypothesis]:
        return self.storage.get_hypotheses(session_id=self.session_id)

    def get_unresolved_hypotheses(self) -> List[Hypothesis]:
        """Which hypotheses remain unresolved?"""
        all_hyp = self.get_hypotheses()
        return [
            h for h in all_hyp
            if h.status in (HypothesisStatus.PROPOSED, HypothesisStatus.ACTIVE, HypothesisStatus.INCONCLUSIVE)
        ]

    # --- Experiments ---

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

        # Update hypothesis evidence graph if hypothesis attached
        if run.hypothesis_id:
            if corr_res.reproduced and "SUPPORTED" in (corr_res.hypothesis_verdict or ""):
                self.add_evidence(
                    hypothesis_id=run.hypothesis_id,
                    evidence_type=EvidenceType.RUN,
                    relation=EvidenceRelation.SUPPORTS,
                    source_agent_id="crosslab-correlator",
                    source_id=str(run.run_id),
                    rationale=corr_res.hypothesis_verdict or f"Correlated discrepancies in Run {run.run_id}",
                    details={"discrepancies_count": len(corr_res.discrepancies)},
                )
            elif not corr_res.reproduced and run.outcome == RunOutcome.NOT_REPRODUCED:
                self.add_evidence(
                    hypothesis_id=run.hypothesis_id,
                    evidence_type=EvidenceType.RUN,
                    relation=EvidenceRelation.CONTRADICTS,
                    source_agent_id="crosslab-correlator",
                    source_id=str(run.run_id),
                    rationale="Run completed without failure reproduction",
                )

        return run

    def get_runs(self) -> List[RunRecord]:
        return self.storage.get_runs(session_id=self.session_id)

    def get_run(self, run_id: int) -> Optional[RunRecord]:
        return self.storage.get_run(run_id, session_id=self.session_id)

    def get_latest_reproducing_run(self) -> Optional[RunRecord]:
        runs = self.get_runs()
        reproduced = [r for r in runs if r.outcome == RunOutcome.REPRODUCED]
        return reproduced[-1] if reproduced else None

    def diff_runs(self, run_id_a: int, run_id_b: int) -> Optional[Dict[str, Any]]:
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
        clock_offset_ms: float = 0.0,
        clock_uncertainty_ms: float = 0.0,
        sequence_num: int = 0,
        causal_parent_id: Optional[str] = None,
        tags: Optional[List[str]] = None,
        notes: Optional[str] = None,
    ) -> Observation:
        obs = Observation(
            session_id=self.session_id,
            run_id=run_id,
            agent_id=agent_id,
            clock_offset_ms=clock_offset_ms,
            clock_uncertainty_ms=clock_uncertainty_ms,
            sequence_num=sequence_num,
            causal_parent_id=causal_parent_id,
            metric_name=metric_name,
            value=value,
            unit=unit,
            tags=tags or [],
            notes=notes,
        )
        self.storage.save_observation(obs)
        run = self.get_run(run_id)
        if run:
            run.observations.append(obs)
            self.record_run(run)
        return obs

    def get_observations(self, run_id: Optional[int] = None) -> List[Observation]:
        return self.storage.get_observations(session_id=self.session_id, run_id=run_id)

    def get_contradicting_observations(self, hypothesis_id: str) -> List[Observation]:
        hyp = self.storage.get_hypothesis(hypothesis_id)
        if not hyp:
            return []
        contradicting_run_ids = hyp.contradicting_run_ids
        if not contradicting_run_ids:
            return []
        contradicting_obs = []
        for run_id in contradicting_run_ids:
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
