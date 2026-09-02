# CrossLab Investigation Protocol Rules

These rules guide all autonomous coding agents collaborating across machines via CrossLab:

1. **Zero-Implicit-Trust**:
   - Never request or attempt arbitrary remote shell execution on a peer's machine.
   - Always formulate requests as structured proposals (`request_instrumentation`, `propose_experiment`).
2. **First-Class Evidence**:
   - Never assert confidence without citing concrete evidence links (`run_id`, `observation_id`, timestamped packet log).
   - Use `crosslab_add_evidence` with explicit relations (`supports`, `contradicts`, `qualifies`).
3. **Barrier Synchronization**:
   - Before executing a test run, ensure both agents have signaled `ready`.
   - Start and stop telemetry collection within the coordinated run window.
4. **Time & Sequence Precision**:
   - Always record sequence numbers (`packet_id`, `frame_seq`) and high-resolution monotonic timestamps.
   - Allow for clock uncertainty ($\pm \Delta t$) when correlating timestamps across distributed networks.
5. **Post-Run Record Closure**:
   - Immediately upon concluding analysis of a test run, update the run record in storage with its final outcome (`reproduced`, `success`, `timeout`, `crash`, etc.) and a concise `result_summary` of the findings.
   - Never leave completed test runs in `pending` status once evidence evaluation is finished.
