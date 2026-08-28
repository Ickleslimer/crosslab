import hashlib
from pathlib import Path


PROBE = (
    Path(__file__).parents[1]
    / "crosslab"
    / "cases"
    / "fear3"
    / "probes"
    / "fear3_steam_probe.js"
)


def test_run20_is_passive_and_gameplay_gated() -> None:
    source = PROBE.read_text(encoding="utf-8")

    assert "Run 20 is observational" in source
    assert "this.channel === 4098 && messageSize > 0" in source
    assert "Run20Telemetry ACTIVE" in source
    assert "retval.replace(0)" not in source
    assert "DROPPED ReadP2PPacket" not in source


def test_run20_traces_auth_ticket_lifecycle_and_callback_results() -> None:
    source = PROBE.read_text(encoding="utf-8")

    assert "GetAuthSessionTicket" in source
    assert "BeginAuthSession" in source
    assert "CancelAuthTicket" in source
    assert 'findExport("SteamAPI_RunCallbacks")' in source
    assert 'findExport("Steam_BGetCallback")' in source
    assert "LegacyCallbackDispatchNoTry" in source
    assert "LegacyCallbackDispatchTryCatch" in source
    assert "opcode signature mismatch" in source
    assert "ValidateAuthTicketResponse_t" in source
    assert "GetAuthSessionTicketResponse_t" in source
    assert "AuthTicketInvalidAlreadyUsed" in source


def test_run20_traces_relevant_dialog_paths() -> None:
    source = PROBE.read_text(encoding="utf-8")

    assert "DialogText api=" in source
    assert "DialogLiteralAccess" in source
    assert '"Failed authentication!"' in source
    assert '"Kicked by the host"' in source
    assert '"Connection lost"' in source


def test_stack_traces_use_module_relative_addresses_as_authority() -> None:
    source = PROBE.read_text(encoding="utf-8")

    assert "Process.findModuleByAddress(address)" in source
    assert "address.sub(owner.base)" in source
    assert "nearest_symbol_hint=" in source
    assert ".map(stackFrame)" in source
    assert ".map(DebugSymbol.fromAddress)" not in source


def test_run21_preflight_is_pinned_to_reviewed_images_and_full_signatures() -> None:
    source = PROBE.read_text(encoding="utf-8")

    assert "b9aefdbee81d92296532a17b2032a5731e40026d04026a8194cb9125a6a6c915" in source
    assert "75de00444dede8c95a94b3c283a0292f33e40005e29c669fd112cbb9d44876d7" in source
    assert "peTimestamp: 0x4e0d0b76" in source
    assert "sizeOfImage: 0x15e2000" in source
    assert "peTimestamp: 0x6a70ef0e" in source
    assert "sizeOfImage: 0x1498000" in source
    assert "File.readAllBytes" in source
    assert 'Checksum.compute("sha256"' in source
    assert "0x0f, 0xb7, 0x4f, 0x06" in source
    assert "0x14, 0x51, 0x8b, 0x4c" in source
    assert "0x4c, 0x24, 0x10, 0x51, 0x8b, 0xc8, 0xff, 0xd2" in source
    assert "0x53, 0x8b, 0x10, 0x8b, 0xc8, 0x8b, 0x42, 0x10, 0xff, 0xd0" in source
    assert "0xe8, 0x6e, 0xe7, 0x66, 0x00" in source
    assert "0xe8, 0x78, 0xfe, 0xe0, 0xff" in source
    assert "RUN21 PREFLIGHT ABORT" in source


def test_run21_breadcrumbs_are_bounded_and_same_thread_correlated() -> None:
    source = PROBE.read_text(encoding="utf-8")

    assert "maxAgeMs: 250" in source
    assert "maxEventsPerTid: 32" in source
    assert "ringsByTid" in source
    assert "sameTidBreadcrumbWindow" in source
    assert "separateCrossThreadWindows" in source
    assert "same_tid_breadcrumbs" in source
    assert "cross_thread_breadcrumbs_separate" in source
    assert "fear3_close_call_924084" in source
    assert "fear3_breadcrumb_indirect_0187f9" in source
    assert "fear3_breadcrumb_relative_0b12bd" in source
    assert "fear3_breadcrumb_relative_448653" in source


def test_run21_requires_authoritative_live_close_target_owner_and_rva() -> None:
    source = PROBE.read_text(encoding="utf-8")

    assert "closeChannelRva: 0x611960" in source
    assert "Process.findModuleByAddress(closeTarget)" in source
    assert 'owner.name.toLowerCase() !== run21ReviewedManifest.steamclient.moduleName.toLowerCase()' in source
    assert "closeTargetRva !== run21ReviewedManifest.steamclient.closeChannelRva" in source
    assert "Run21 live-owner preflight OK" in source
    assert "nearest_symbol_hint=disabled_for_acceptance" in source


def test_run21_optional_exports_are_raw_only_and_rate_bounded() -> None:
    source = PROBE.read_text(encoding="utf-8")

    assert 'attachRawOptionalExport("Steam_NotifyMissingInterface")' in source
    assert 'attachRawOptionalExport("Steam_IsKnownInterface")' in source
    assert 'findModuleExport("steamclient.dll", exportName)' in source
    assert "optionalRawExportListeners" in source
    assert "optional export group disabled safely" in source
    assert "untrackListener(listener)" in source
    assert "rawRegisterSnapshot" in source
    assert "rawStackWords" in source
    assert "raw_retval_bits" in source
    assert 'abi_decoding: "unrecovered_raw_bits_only"' in source
    assert "windowCount > 1000" in source
    assert "listener.detach()" in source
    assert "retval.replace(" not in source


def test_run21_non_function_entry_sites_use_read_only_stalker_callouts() -> None:
    source = PROBE.read_text(encoding="utf-8")

    assert "Stalker.follow(tid" in source
    assert "transform: run21StalkerTransform" in source
    assert "instruction.address.equals(run21InstructionSites.close.address)" in source
    assert "instruction.address.equals(run21InstructionSites.indirect.address)" in source
    assert "iterator.putCallout(function(cpuContext)" in source
    assert "recordCallerBreadcrumb(calloutSite.id, calloutSite.rva, cpuContext)" in source
    assert "iterator.keep();" in source
    assert source.count("iterator.keep();") == 1
    assert "callerHooks" not in source
    assert "safeAttach(\n                run21MainModule.base.add(hook.rva)" not in source
    assert "Interceptor.attach(run21InstructionSites.close.address" not in source
    assert "Interceptor.attach(run21InstructionSites.indirect.address" not in source
    assert "retval.replace(" not in source


def test_run21_stalker_lifecycle_is_minimal_bounded_and_fail_closed() -> None:
    source = PROBE.read_text(encoding="utf-8")

    assert "maxFollowedThreads: 1" in source
    assert "maxFollowDurationMs: 180000" in source
    assert "captureStopped: false" in source
    assert "run21InstrumentationFailedClosed || run21CallerEvidence.captureStopped" in source
    assert "unexpected second Stalker thread" in source
    assert "stopRun21StalkerThread" in source
    assert "Stalker.unfollow(tid)" in source
    assert "Stalker.garbageCollect()" in source
    assert "cleanupRun21Instrumentation" in source
    assert "RUN21 FAIL-CLOSED CLEANUP" in source
    assert "requiredAttach" in source
    assert "required hook failed" in source
    assert "requiredAttach(\n            run21InstructionSites.stalkerAnchor.address" in source
    assert 'requiredAttach(sendP2P, "Run21 SendP2PPacket"' in source
    assert 'requiredAttach(readP2P, "Run21 ReadP2PPacket"' in source
    assert 'requiredAttach(sessionSlots[5], "Run21 CloseP2PChannelWithUser target"' in source
    assert "first CloseP2PChannelWithUser captured" in source
    assert 'stopRun21StalkerThread(tid, "180s hard timeout", true)' in source


def test_run21_missing_required_modules_fail_closed() -> None:
    source = PROBE.read_text(encoding="utf-8")

    assert 'throw new Error("required main module is not available")' in source
    assert "RUN21 PREFLIGHT ABORT: required steam_api.dll/steam_api64.dll is not loaded" in source
    assert "throw error;" in source
    assert "steam_api.dll not yet loaded; waiting" not in source


def test_run21_probe_hashes_match_reviewed_candidate() -> None:
    # This is the pre-launch probe-artifact gate.  Runtime PE/signature checks
    # then run before the first Interceptor.attach inside the agent.
    canonical = PROBE.read_text(encoding="utf-8").encode("utf-8")
    git_blob = hashlib.sha1(
        b"blob " + str(len(canonical)).encode("ascii") + b"\0" + canonical
    ).hexdigest()
    sha256 = hashlib.sha256(canonical).hexdigest()

    assert git_blob == "2fadde5a570e57f819b8d35bf8f7b3795a367f2f"
    assert sha256 == "7e238a633c32b9073364973ac919fac5c17806f0d40bbc67dcfa50f1a43edee6"
