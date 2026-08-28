/**
 * FEAR 3 Steam P2P Diagnostic Probe (Frida Hook Script)
 * Intercepts packet I/O, legacy P2P session lifecycle, Steam auth-ticket
 * calls/callbacks, and likely user-facing error-dialog paths.
 * 
 * Usage:
 *   frida -n "F.E.A.R. 3.exe" -l fear3_steam_probe.js
 */

console.log("[CrossLab Probe] Initializing Steam networking hooks in Fear3.exe...");

const steamApi = Process.findModuleByName("steam_api.dll") || Process.findModuleByName("steam_api64.dll");

if (steamApi) {
    console.log(`[CrossLab Probe] Found steam_api at ${steamApi.base}`);

    // Run 21 is tied to the exact images reviewed after Run 20.  Refuse to
    // install any hook when the executable, Steam client, or caller bytes do
    // not match this manifest.  The probe artifact SHA-256 is verified by the
    // test/build gate before Frida is launched and is reported with every
    // candidate; unlike the PE identities it cannot be self-hashed reliably
    // from inside an already-loaded Frida script.
    const run21ReviewedManifest = {
        fear3: {
            moduleName: "F.E.A.R. 3.exe",
            sha256: "b9aefdbee81d92296532a17b2032a5731e40026d04026a8194cb9125a6a6c915",
            peTimestamp: 0x4e0d0b76,
            sizeOfImage: 0x15e2000
        },
        steamclient: {
            moduleName: "steamclient.dll",
            sha256: "75de00444dede8c95a94b3c283a0292f33e40005e29c669fd112cbb9d44876d7",
            peTimestamp: 0x6a70ef0e,
            sizeOfImage: 0x1498000,
            closeChannelRva: 0x611960
        },
        callerSignatures: [
            {
                label: "close_call_window",
                rva: 0x92406e,
                bytes: [
                    0x0f, 0xb7, 0x4f, 0x06, 0x8b, 0x10, 0x8b, 0x52,
                    0x14, 0x51, 0x8b, 0x4c, 0x24, 0x10, 0x51, 0x8b,
                    0x4c, 0x24, 0x10, 0x51, 0x8b, 0xc8, 0xff, 0xd2
                ]
            },
            {
                label: "breadcrumb_indirect_call_window",
                rva: 0x0187f1,
                bytes: [0x53, 0x8b, 0x10, 0x8b, 0xc8, 0x8b, 0x42, 0x10, 0xff, 0xd0]
            },
            {
                label: "breadcrumb_relative_call_1",
                rva: 0x0b12bd,
                bytes: [0xe8, 0x6e, 0xe7, 0x66, 0x00]
            },
            {
                label: "breadcrumb_relative_call_2",
                rva: 0x448653,
                bytes: [0xe8, 0x78, 0xfe, 0xe0, 0xff]
            }
        ]
    };

    const bytesMatch = function(address, expected) {
        try {
            const actual = new Uint8Array(address.readByteArray(expected.length));
            for (let index = 0; index < expected.length; index++) {
                if (actual[index] !== expected[index]) {
                    return false;
                }
            }
            return true;
        } catch (_) {
            return false;
        }
    };

    const peIdentity = function(module) {
        const peOffset = module.base.add(0x3c).readU32();
        const ntHeaders = module.base.add(peOffset);
        if (ntHeaders.readU32() !== 0x00004550) {
            throw new Error(`${module.name} has no PE signature`);
        }
        return {
            peTimestamp: ntHeaders.add(8).readU32(),
            sizeOfImage: ntHeaders.add(0x50).readU32()
        };
    };

    const fileSha256 = function(path) {
        if (typeof File === "undefined" ||
            typeof File.readAllBytes !== "function" ||
            typeof Checksum === "undefined" ||
            typeof Checksum.compute !== "function") {
            throw new Error("Frida File.readAllBytes/Checksum.compute unavailable");
        }
        return Checksum.compute("sha256", File.readAllBytes(path)).toLowerCase();
    };

    const validateReviewedImage = function(module, expected) {
        if (!module) {
            throw new Error(`required module ${expected.moduleName} is not loaded`);
        }
        const identity = peIdentity(module);
        const sha256 = fileSha256(module.path);
        const mismatches = [];
        if (module.name.toLowerCase() !== expected.moduleName.toLowerCase()) {
            mismatches.push(`name=${module.name}`);
        }
        if (sha256 !== expected.sha256) {
            mismatches.push(`sha256=${sha256}`);
        }
        if (identity.peTimestamp !== expected.peTimestamp) {
            mismatches.push(`pe_timestamp=0x${identity.peTimestamp.toString(16)}`);
        }
        if (identity.sizeOfImage !== expected.sizeOfImage || module.size !== expected.sizeOfImage) {
            mismatches.push(`size_of_image=0x${identity.sizeOfImage.toString(16)} module_size=0x${module.size.toString(16)}`);
        }
        if (mismatches.length > 0) {
            throw new Error(`${expected.moduleName} manifest mismatch: ${mismatches.join(" ")}`);
        }
        console.log(`[CrossLab Probe] Run21 manifest OK ${module.name} sha256=${sha256} pe_timestamp=0x${identity.peTimestamp.toString(16)} size_of_image=0x${identity.sizeOfImage.toString(16)}`);
    };

    const run21MainModule = Process.mainModule;
    const run21SteamClient = Process.findModuleByName("steamclient.dll");
    try {
        validateReviewedImage(run21MainModule, run21ReviewedManifest.fear3);
        validateReviewedImage(run21SteamClient, run21ReviewedManifest.steamclient);
        for (const signature of run21ReviewedManifest.callerSignatures) {
            const address = run21MainModule.base.add(signature.rva);
            if (!bytesMatch(address, signature.bytes)) {
                throw new Error(`${signature.label} signature mismatch at ${run21MainModule.name}+0x${signature.rva.toString(16)}`);
            }
        }
        console.log("[CrossLab Probe] Run21 caller signature preflight OK; packet mutation remains disabled");
    } catch (error) {
        console.log(`[CrossLab Probe] RUN21 PREFLIGHT ABORT: ${error}`);
        throw error;
    }

    // Run 20 is observational. Packet suppression is deliberately absent:
    // Runs 18 and 19 showed that dropping either candidate control frame only
    // perturbs the authentication failure mode.
    const run20Telemetry = {
        gameplayStarted: false,
        sendFailures: 0,
        lastSentPacket: null,
        callbackPumpCount: 0,
        callbackDispatchCount: 0,
        activeCallbackPump: null
    };

    // Frida 17 moved export lookup from the global Module namespace to the
    // Module instance. Keep the fallback so the probe also works on older
    // Frida releases.
    const findExport = function(name) {
        if (typeof steamApi.findExportByName === "function") {
            return steamApi.findExportByName(name);
        }
        if (typeof Module.findExportByName === "function") {
            return Module.findExportByName(steamApi.name, name);
        }
        return null;
    };

    const findModuleExport = function(moduleName, name) {
        const module = Process.findModuleByName(moduleName);
        if (module && typeof module.findExportByName === "function") {
            return module.findExportByName(name);
        }
        if (typeof Module.findExportByName === "function") {
            return Module.findExportByName(moduleName, name);
        }
        return null;
    };

    const safeAttach = function(address, label, callbacks) {
        if (!address || address.isNull()) {
            console.log(`  [-] Could not resolve ${label}`);
            return false;
        }
        try {
            Interceptor.attach(address, callbacks);
            console.log(`  [+] Attached ${label} at ${address}`);
            return true;
        } catch (error) {
            console.log(`  [-] Could not attach ${label} at ${address}: ${error}`);
            return false;
        }
    };

    const stackFrame = function(address) {
        const rawAddress = address.toString();
        try {
            const owner = Process.findModuleByAddress(address);
            if (!owner) {
                return `${rawAddress} <no-module>`;
            }

            // DebugSymbol may select a nearby public export from the wrong
            // internal routine.  It is deliberately only a hint; raw address
            // plus owner module and RVA are the authoritative identity.
            let nearestSymbolHint = "";
            try {
                const symbol = DebugSymbol.fromAddress(address);
                if (symbol && symbol.name) {
                    nearestSymbolHint = ` nearest_symbol_hint=${symbol.moduleName || "unknown-module"}!${symbol.name}`;
                }
            } catch (_) {}
            return `${rawAddress} ${owner.name}+${address.sub(owner.base)}${nearestSymbolHint}`;
        } catch (error) {
            return `${rawAddress} <frame unavailable: ${error}>`;
        }
    };

    const stackTrace = function(context) {
        try {
            return Thread.backtrace(context, Backtracer.ACCURATE)
                .map(stackFrame)
                .join(" <- ");
        } catch (error) {
            return `<stack unavailable: ${error}>`;
        }
    };

    const steamIdKey = function(low, high) {
        return `0x${high.toString(16).padStart(8, "0")}${low.toString(16).padStart(8, "0")}`;
    };

    const lastSentSummary = function() {
        const packet = run20Telemetry.lastSentPacket;
        if (!packet) {
            return `last_sent_packet=none send_failures=${run20Telemetry.sendFailures}`;
        }
        return `last_sent_packet=#${packet.id}/${packet.size}B/ch${packet.channel}${packet.preview} result=${packet.success} send_failures=${run20Telemetry.sendFailures}`;
    };

    // Newer Steamworks SDKs expose flat wrapper functions. FEAR 3 ships an
    // older 32-bit steam_api.dll that only exports SteamNetworking(), so fall
    // back to ISteamNetworking's vtable (Send=slot 0, Read=slot 2).
    let legacyVtable = false;
    let legacyNetworkingVtable = null;
    let sendP2P = findExport("SteamAPI_ISteamNetworking_SendP2PPacket");
    let readP2P = findExport("SteamAPI_ISteamNetworking_ReadP2PPacket");

    if (!sendP2P || !readP2P) {
        const networkingFactory = findExport("SteamNetworking");
        if (networkingFactory) {
            const getNetworking = new NativeFunction(networkingFactory, "pointer", []);
            const networking = getNetworking();
            if (!networking.isNull()) {
                const vtable = networking.readPointer();
                legacyNetworkingVtable = vtable;
                sendP2P = vtable.readPointer();
                readP2P = vtable.add(2 * Process.pointerSize).readPointer();
                legacyVtable = true;
                console.log(`[CrossLab Probe] Using legacy ISteamNetworking vtable at ${vtable}`);
            }
        }
    }

    const rawRegisterSnapshot = function(context) {
        const names = Process.pointerSize === 4
            ? ["eax", "ebx", "ecx", "edx", "esi", "edi", "ebp", "esp"]
            : ["rax", "rbx", "rcx", "rdx", "rsi", "rdi", "rbp", "rsp"];
        const snapshot = {};
        for (const name of names) {
            if (context[name] !== undefined) {
                snapshot[name] = context[name].toString();
            }
        }
        return snapshot;
    };

    const rawStackWords = function(context, count) {
        const words = [];
        const stackPointer = Process.pointerSize === 4 ? context.esp : context.rsp;
        if (!stackPointer) {
            return words;
        }
        for (let index = 0; index < count; index++) {
            try {
                words.push(stackPointer.add(index * Process.pointerSize).readPointer().toString());
            } catch (error) {
                words.push(`<unreadable:${error}>`);
                break;
            }
        }
        return words;
    };

    const run21CallerEvidence = {
        maxAgeMs: 250,
        maxEventsPerTid: 32,
        ringsByTid: {},
        firstCloseCaptured: false
    };

    const currentTid = function() {
        return Process.getCurrentThreadId();
    };

    const trimTidRing = function(tid, nowMs) {
        const key = tid.toString();
        const existing = run21CallerEvidence.ringsByTid[key] || [];
        const recent = existing.filter(event => nowMs - event.wallMs <= run21CallerEvidence.maxAgeMs);
        if (recent.length > run21CallerEvidence.maxEventsPerTid) {
            recent.splice(0, recent.length - run21CallerEvidence.maxEventsPerTid);
        }
        run21CallerEvidence.ringsByTid[key] = recent;
        return recent;
    };

    const recordCallerBreadcrumb = function(callSiteId, callSiteRva, context) {
        const tid = currentTid();
        const nowMs = Date.now();
        const ring = trimTidRing(tid, nowMs);
        ring.push({
            call_site_id: callSiteId,
            module: run21MainModule.name,
            rva: `0x${callSiteRva.toString(16)}`,
            tid: tid,
            wallMs: nowMs,
            registers: rawRegisterSnapshot(context),
            stack_words: rawStackWords(context, 8)
        });
        if (ring.length > run21CallerEvidence.maxEventsPerTid) {
            ring.shift();
        }
    };

    const sameTidBreadcrumbWindow = function(tid, nowMs) {
        return trimTidRing(tid, nowMs).map(event => ({
            call_site_id: event.call_site_id,
            module: event.module,
            rva: event.rva,
            tid: event.tid,
            age_ms: nowMs - event.wallMs,
            registers: event.registers,
            stack_words: event.stack_words
        }));
    };

    const separateCrossThreadWindows = function(closeTid, nowMs) {
        const windows = {};
        for (const key of Object.keys(run21CallerEvidence.ringsByTid)) {
            if (key === closeTid.toString()) {
                continue;
            }
            const tid = parseInt(key, 10);
            const events = trimTidRing(tid, nowMs);
            if (events.length > 0) {
                windows[key] = events.map(event => ({
                    call_site_id: event.call_site_id,
                    module: event.module,
                    rva: event.rva,
                    tid: event.tid,
                    age_ms: nowMs - event.wallMs
                }));
            }
        }
        return windows;
    };

    if (legacyNetworkingVtable && Process.pointerSize === 4) {
        const closeTarget = legacyNetworkingVtable
            .add(5 * Process.pointerSize)
            .readPointer();
        const owner = Process.findModuleByAddress(closeTarget);
        if (!owner || owner.name.toLowerCase() !== run21ReviewedManifest.steamclient.moduleName.toLowerCase()) {
            throw new Error(`RUN21 PREFLIGHT ABORT: CloseP2PChannelWithUser target ${closeTarget} owner=${owner ? owner.name : "none"}`);
        }
        const closeTargetRva = closeTarget.sub(owner.base).toUInt32();
        if (closeTargetRva !== run21ReviewedManifest.steamclient.closeChannelRva) {
            throw new Error(`RUN21 PREFLIGHT ABORT: CloseP2PChannelWithUser target ${owner.name}+0x${closeTargetRva.toString(16)} expected +0x${run21ReviewedManifest.steamclient.closeChannelRva.toString(16)}`);
        }
        console.log(`[CrossLab Probe] Run21 live-owner preflight OK target=${closeTarget} authority=${owner.name}+0x${closeTargetRva.toString(16)} nearest_symbol_hint=disabled_for_acceptance`);

        const callerHooks = [
            { id: "fear3_close_call_924084", rva: 0x924084 },
            { id: "fear3_breadcrumb_indirect_0187f9", rva: 0x0187f9 },
            { id: "fear3_breadcrumb_relative_0b12bd", rva: 0x0b12bd },
            { id: "fear3_breadcrumb_relative_448653", rva: 0x448653 }
        ];
        for (const hook of callerHooks) {
            safeAttach(
                run21MainModule.base.add(hook.rva),
                `Run21 caller ${hook.id}`,
                {
                    onEnter: function() {
                        recordCallerBreadcrumb(hook.id, hook.rva, this.context);
                    }
                }
            );
        }
    } else {
        throw new Error("RUN21 PREFLIGHT ABORT: reviewed x86 legacy ISteamNetworking vtable unavailable");
    }

    // Hook SteamNetworking005 / ISteamNetworking::SendP2PPacket
    if (sendP2P) {
        let sentPacketCounter = 0;
        Interceptor.attach(sendP2P, {
            onEnter: function(args) {
                if (legacyVtable && Process.pointerSize === 4) {
                    // x86 thiscall keeps `this` in ECX. CSteamID occupies the
                    // first two 32-bit stack slots, shifting the remaining
                    // arguments by one slot compared with a flat wrapper.
                    this.steamIDRemoteLow = args[0].toUInt32();
                    this.steamIDRemoteHigh = args[1].toUInt32();
                    this.pubData = args[2];
                    this.cubData = args[3].toUInt32();
                    this.eP2PSendType = args[4].toInt32();
                    this.channel = args[5].toInt32();
                } else {
                    this.steamIDRemote = args[1];
                    this.pubData = args[2];
                    this.cubData = args[3].toUInt32();
                    this.eP2PSendType = args[4].toInt32();
                    this.channel = args[5].toInt32();
                }
                sentPacketCounter++;
                this.pktId = sentPacketCounter;
            },
            onLeave: function(retval) {
                const success = retval.toInt32() !== 0;
                if (!success) {
                    run20Telemetry.sendFailures++;
                }
                let payloadPreview = "";
                if (this.channel === 4101 || this.cubData <= 32) {
                    try {
                        const bytes = this.pubData.readByteArray(Math.min(this.cubData, 32));
                        const hex = Array.from(new Uint8Array(bytes)).map(b => b.toString(16).padStart(2, '0')).join(' ');
                        payloadPreview = ` hex=[${hex}]`;
                    } catch(e) {}
                }
                run20Telemetry.lastSentPacket = {
                    id: this.pktId,
                    size: this.cubData,
                    channel: this.channel,
                    preview: payloadPreview,
                    success: success
                };
                // Channel 4101 carries the auth/control burst. Log it in full,
                // while sampling the high-volume gameplay channels so callback
                // and dialog evidence cannot be buried by several thousand
                // packet lines per second.
                if (this.channel === 4101 || !success || (this.pktId % 500) === 0) {
                    console.log(`[Client Probe] ${new Date().toISOString()} SendP2PPacket #${this.pktId} (${this.cubData} bytes, channel=${this.channel})${payloadPreview} -> bool: ${success ? "true" : "false"} failures=${run20Telemetry.sendFailures}`);
                }
            }
        });
        console.log(`  [+] Attached SendP2PPacket hook at ${sendP2P}`);
    } else {
        console.log("  [-] Could not resolve SendP2PPacket");
    }

    // Hook SteamNetworking005 / ISteamNetworking::ReadP2PPacket
    if (readP2P) {
        let recvPacketCounter = 0;
        Interceptor.attach(readP2P, {
            onEnter: function(args) {
                if (legacyVtable && Process.pointerSize === 4) {
                    this.pubDest = args[0];
                    this.cubDest = args[1].toUInt32();
                    this.pcubMsgSize = args[2];
                    this.psteamIDRemote = args[3];
                    this.channel = args[4].toInt32();
                } else {
                    this.pubDest = args[1];
                    this.cubDest = args[2].toUInt32();
                    this.pcubMsgSize = args[3];
                    this.psteamIDRemote = args[4];
                    this.channel = args[5].toInt32();
                }
            },
            onLeave: function(retval) {
                const hasPacket = retval.toInt32() !== 0;
                if (hasPacket) {
                    let messageSize = 0;
                    if (this.pcubMsgSize && !this.pcubMsgSize.isNull()) {
                        messageSize = this.pcubMsgSize.readU32();
                    }

                    if (!run20Telemetry.gameplayStarted &&
                        this.channel === 4098 && messageSize > 0) {
                        run20Telemetry.gameplayStarted = true;
                        console.log(`[Client Probe] ${new Date().toISOString()} Run20Telemetry ACTIVE after first channel=4098 gameplay packet (passive; packet drops disabled)`);
                    }

                    recvPacketCounter++;
                    let payloadPreview = "";
                    if (this.channel === 4101 || messageSize <= 32) {
                        try {
                            const bytes = this.pubDest.readByteArray(Math.min(messageSize, 32));
                            const hex = Array.from(new Uint8Array(bytes)).map(b => b.toString(16).padStart(2, '0')).join(' ');
                            payloadPreview = ` hex=[${hex}]`;
                        } catch(e) {}
                    }
                    if (this.channel === 4101 || (recvPacketCounter % 500) === 0) {
                        console.log(`[Client Probe] ${new Date().toISOString()} ReadP2PPacket #${recvPacketCounter} (${messageSize} bytes, channel=${this.channel})${payloadPreview} -> bool: true`);
                    }
                }
            }
        });
        console.log(`  [+] Attached ReadP2PPacket hook at ${readP2P}`);
    } else {
        console.log("  [-] Could not resolve ReadP2PPacket");
    }

    // FEAR 3 uses the legacy 32-bit ISteamNetworking interface. Trace the
    // session-management methods that can explain a deterministic teardown:
    // slots 3-7 are Accept, Close, CloseChannel, GetState, and AllowRelay.
    if (legacyNetworkingVtable && Process.pointerSize === 4) {
        const sessionSlots = [];
        for (let slot = 3; slot <= 7; slot++) {
            sessionSlots[slot] = legacyNetworkingVtable
                .add(slot * Process.pointerSize)
                .readPointer();
        }

        Interceptor.attach(sessionSlots[3], {
            onEnter: function(args) {
                this.remote = steamIdKey(args[0].toUInt32(), args[1].toUInt32());
                this.trace = stackTrace(this.context);
            },
            onLeave: function(retval) {
                console.log(`[Client Probe] ${new Date().toISOString()} AcceptP2PSessionWithUser remote=${this.remote} -> bool=${retval.toInt32() !== 0} stack=${this.trace}`);
            }
        });

        Interceptor.attach(sessionSlots[4], {
            onEnter: function(args) {
                const remote = steamIdKey(args[0].toUInt32(), args[1].toUInt32());
                console.log(`[Client Probe] ${new Date().toISOString()} CloseP2PSessionWithUser remote=${remote} ${lastSentSummary()} stack=${stackTrace(this.context)}`);
            }
        });

        Interceptor.attach(sessionSlots[5], {
            onEnter: function(args) {
                const nowMs = Date.now();
                const tid = currentTid();
                const remoteLow = args[0].toUInt32();
                const remoteHigh = args[1].toUInt32();
                const channel = args[2].toInt32();
                const evidence = {
                    event: "Run21CloseP2PChannelEvidence",
                    first_close: !run21CallerEvidence.firstCloseCaptured,
                    timestamp: new Date(nowMs).toISOString(),
                    tid: tid,
                    remote: steamIdKey(remoteLow, remoteHigh),
                    raw_arguments: {
                        steam_id_low: `0x${remoteLow.toString(16).padStart(8, "0")}`,
                        steam_id_high: `0x${remoteHigh.toString(16).padStart(8, "0")}`,
                        channel_bits: `0x${(channel >>> 0).toString(16).padStart(8, "0")}`
                    },
                    registers: rawRegisterSnapshot(this.context),
                    stack_words: rawStackWords(this.context, 8),
                    same_tid_breadcrumbs: sameTidBreadcrumbWindow(tid, nowMs),
                    cross_thread_breadcrumbs_separate: separateCrossThreadWindows(tid, nowMs),
                    authoritative_stack: stackTrace(this.context),
                    last_sent_packet: lastSentSummary()
                };
                run21CallerEvidence.firstCloseCaptured = true;
                console.log(`[Client Probe] ${JSON.stringify(evidence)}`);
            }
        });

        const lastSessionStates = {};
        Interceptor.attach(sessionSlots[6], {
            onEnter: function(args) {
                this.remote = steamIdKey(args[0].toUInt32(), args[1].toUInt32());
                this.state = args[2];
            },
            onLeave: function(retval) {
                const success = retval.toInt32() !== 0;
                let snapshot = `success=${success}`;
                try {
                    if (success && this.state && !this.state.isNull()) {
                        snapshot = [
                            `active=${this.state.readU8()}`,
                            `connecting=${this.state.add(1).readU8()}`,
                            `error=${this.state.add(2).readU8()}`,
                            `relay=${this.state.add(3).readU8()}`,
                            `bytesQueued=${this.state.add(4).readS32()}`,
                            `packetsQueued=${this.state.add(8).readS32()}`
                        ].join(" ");
                    }
                } catch (error) {
                    snapshot += ` parse_error=${error}`;
                }
                if (lastSessionStates[this.remote] !== snapshot) {
                    lastSessionStates[this.remote] = snapshot;
                    console.log(`[Client Probe] ${new Date().toISOString()} GetP2PSessionState remote=${this.remote} ${snapshot}`);
                }
            }
        });

        Interceptor.attach(sessionSlots[7], {
            onEnter: function(args) {
                console.log(`[Client Probe] ${new Date().toISOString()} AllowP2PPacketRelay allow=${args[0].toInt32() !== 0} stack=${stackTrace(this.context)}`);
            }
        });

        console.log(`  [+] Attached legacy session hooks: Accept=${sessionSlots[3]} Close=${sessionSlots[4]} CloseChannel=${sessionSlots[5]} GetState=${sessionSlots[6]} AllowRelay=${sessionSlots[7]}`);
    }

    // Optional falsification hooks for the two exact steamclient exports that
    // DebugSymbol previously confused with the internal close target.  Their
    // ABI is unrecovered: capture raw machine state only.  In particular, do
    // not dereference arguments or interpret return/null bits as an interface,
    // string, pointer, or boolean.
    const attachRawOptionalExport = function(exportName) {
        const address = run21SteamClient.findExportByName(exportName);
        if (!address) {
            console.log(`  [-] Optional exact export unavailable: ${exportName}`);
            return;
        }
        const owner = Process.findModuleByAddress(address);
        const authority = owner
            ? `${owner.name}+${address.sub(owner.base)}`
            : "<no-module>";
        let windowStartMs = Date.now();
        let windowCount = 0;
        let totalCount = 0;
        let detached = false;
        let listener = null;
        listener = Interceptor.attach(address, {
            onEnter: function() {
                const nowMs = Date.now();
                if (nowMs - windowStartMs >= 1000) {
                    windowStartMs = nowMs;
                    windowCount = 0;
                }
                windowCount++;
                totalCount++;
                if (windowCount > 1000) {
                    if (!detached) {
                        detached = true;
                        console.log(`[Client Probe] Run21OptionalExport ABORT export=${exportName} reason=rate_over_1000_per_s total=${totalCount}`);
                        setImmediate(function() {
                            listener.detach();
                        });
                    }
                    return;
                }
                this.run21RawExport = {
                    event: "Run21OptionalExportRaw",
                    phase: "enter",
                    timestamp: new Date(nowMs).toISOString(),
                    export: exportName,
                    exact_address: address.toString(),
                    authority: authority,
                    entry_count: totalCount,
                    tid: currentTid(),
                    registers: rawRegisterSnapshot(this.context),
                    stack_words: rawStackWords(this.context, 8),
                    abi_decoding: "unrecovered_raw_bits_only"
                };
                console.log(`[Client Probe] ${JSON.stringify(this.run21RawExport)}`);
            },
            onLeave: function(retval) {
                if (!this.run21RawExport || detached) {
                    return;
                }
                console.log(`[Client Probe] ${JSON.stringify({
                    event: "Run21OptionalExportRaw",
                    phase: "leave",
                    timestamp: new Date().toISOString(),
                    export: exportName,
                    exact_address: address.toString(),
                    authority: authority,
                    entry_count: this.run21RawExport.entry_count,
                    tid: this.run21RawExport.tid,
                    raw_retval_bits: retval.toString(),
                    abi_decoding: "unrecovered_raw_bits_only"
                })}`);
            }
        });
        console.log(`  [+] Attached raw-only optional export ${exportName} at ${address} authority=${authority}`);
    };

    attachRawOptionalExport("Steam_NotifyMissingInterface");
    attachRawOptionalExport("Steam_IsKnownInterface");

    // The 2011-era ISteamUser interface used by FEAR 3 exposes auth-ticket
    // lifecycle methods in vtable slots 13-16. These calls reveal whether the
    // repeatable ~102-second cutoff is driven by ticket cancellation/expiry.
    const beginAuthResultNames = {
        0: "OK",
        1: "InvalidTicket",
        2: "DuplicateRequest",
        3: "InvalidVersion",
        4: "GameMismatch",
        5: "ExpiredTicket"
    };
    const authTicketCreatedAt = {};
    const steamUserFactory = findExport("SteamUser");
    if (steamUserFactory && Process.pointerSize === 4) {
        const getSteamUser = new NativeFunction(steamUserFactory, "pointer", []);
        const steamUser = getSteamUser();
        if (!steamUser.isNull()) {
            const userVtable = steamUser.readPointer();
            const authSlots = [];
            for (let slot = 13; slot <= 16; slot++) {
                authSlots[slot] = userVtable.add(slot * Process.pointerSize).readPointer();
            }

            Interceptor.attach(authSlots[13], {
                onEnter: function(args) {
                    this.ticketSize = args[2];
                    this.trace = stackTrace(this.context);
                },
                onLeave: function(retval) {
                    let size = 0;
                    try {
                        if (this.ticketSize && !this.ticketSize.isNull()) {
                            size = this.ticketSize.readU32();
                        }
                    } catch (_) {}
                    const handle = retval.toUInt32();
                    if (handle !== 0) {
                        authTicketCreatedAt[handle] = Date.now();
                    }
                    console.log(`[Client Probe] ${new Date().toISOString()} GetAuthSessionTicket handle=${handle} size=${size} stack=${this.trace}`);
                }
            });

            Interceptor.attach(authSlots[14], {
                onEnter: function(args) {
                    this.ticketBytes = args[1].toUInt32();
                    this.remote = steamIdKey(args[2].toUInt32(), args[3].toUInt32());
                    this.trace = stackTrace(this.context);
                },
                onLeave: function(retval) {
                    const result = retval.toInt32();
                    const resultName = beginAuthResultNames[result] || "Unknown";
                    console.log(`[Client Probe] ${new Date().toISOString()} BeginAuthSession remote=${this.remote} ticketBytes=${this.ticketBytes} result=${result}/${resultName} stack=${this.trace}`);
                }
            });

            Interceptor.attach(authSlots[15], {
                onEnter: function(args) {
                    const remote = steamIdKey(args[0].toUInt32(), args[1].toUInt32());
                    console.log(`[Client Probe] ${new Date().toISOString()} EndAuthSession remote=${remote} stack=${stackTrace(this.context)}`);
                }
            });

            Interceptor.attach(authSlots[16], {
                onEnter: function(args) {
                    const handle = args[0].toUInt32();
                    const createdAt = authTicketCreatedAt[handle];
                    const ageMs = createdAt ? Date.now() - createdAt : null;
                    console.log(`[Client Probe] ${new Date().toISOString()} CancelAuthTicket handle=${handle} age_ms=${ageMs === null ? "unknown" : ageMs} stack=${stackTrace(this.context)}`);
                }
            });

            console.log(`  [+] Attached legacy auth hooks: GetTicket=${authSlots[13]} Begin=${authSlots[14]} End=${authSlots[15]} Cancel=${authSlots[16]}`);
        }
    }

    // SteamAPI_RunCallbacks ultimately consumes CallbackMsg_t records. The
    // legacy Steam_BGetCallback export gives us the callback id and payload
    // before FEAR 3 dispatches it, even when callback objects were registered
    // before Frida attached.
    const authSessionResponseNames = {
        0: "OK",
        1: "UserNotConnectedToSteam",
        2: "NoLicenseOrExpired",
        3: "VACBanned",
        4: "LoggedInElseWhere",
        5: "VACCheckTimedOut",
        6: "AuthTicketCanceled",
        7: "AuthTicketInvalidAlreadyUsed",
        8: "AuthTicketInvalid",
        9: "PublisherIssuedBan",
        10: "AuthTicketNetworkIdentityFailure"
    };
    const steamResultNames = {
        1: "OK",
        2: "Fail",
        3: "NoConnection",
        5: "InvalidPassword",
        6: "LoggedInElsewhere",
        7: "InvalidProtocolVer",
        8: "InvalidParam",
        9: "FileNotFound",
        15: "AccessDenied",
        16: "Timeout",
        17: "Banned",
        18: "AccountNotFound",
        25: "LimitExceeded"
    };
    const callbackNames = {
        101: "SteamServersConnected_t",
        102: "SteamServerConnectFailure_t",
        103: "SteamServersDisconnected_t",
        143: "ValidateAuthTicketResponse_t",
        163: "GetAuthSessionTicketResponse_t"
    };

    const bytePreview = function(buffer, size) {
        if (!buffer || buffer.isNull() || size <= 0) {
            return "";
        }
        try {
            const bytes = buffer.readByteArray(Math.min(size, 32));
            return Array.from(new Uint8Array(bytes))
                .map(b => b.toString(16).padStart(2, "0"))
                .join(" ");
        } catch (error) {
            return `<unreadable: ${error}>`;
        }
    };

    const decodeSteamCallback = function(callbackId, payload, payloadSize) {
        let decoded = "";
        try {
            if (callbackId === 143 && payloadSize >= 12) {
                const steamId = steamIdKey(payload.readU32(), payload.add(4).readU32());
                const response = payload.add(8).readS32();
                const responseName = authSessionResponseNames[response] || "Unknown";
                let owner = "unavailable";
                if (payloadSize >= 20) {
                    owner = steamIdKey(payload.add(12).readU32(), payload.add(16).readU32());
                }
                decoded = ` steam_id=${steamId} auth_response=${response}/${responseName} owner=${owner}`;
            } else if (callbackId === 163 && payloadSize >= 8) {
                const handle = payload.readU32();
                const result = payload.add(4).readS32();
                decoded = ` ticket_handle=${handle} result=${result}/${steamResultNames[result] || "Unknown"}`;
            } else if ((callbackId === 102 || callbackId === 103) && payloadSize >= 4) {
                const result = payload.readS32();
                decoded = ` result=${result}/${steamResultNames[result] || "Unknown"}`;
            }
        } catch (error) {
            decoded = ` decode_error=${error}`;
        }
        return decoded;
    };

    const recordCallbackDispatch = function(source, callbackId, payload, payloadSize, trace) {
        run20Telemetry.callbackDispatchCount++;
        const callbackName = callbackNames[callbackId] || "UnknownSteamUserCallback";
        const decoded = decodeSteamCallback(callbackId, payload, payloadSize);
        const preview = bytePreview(payload, payloadSize);
        const line = `${source} callback=${callbackId}/${callbackName} size=${payloadSize}${decoded} hex=[${preview}]`;
        if (run20Telemetry.activeCallbackPump) {
            run20Telemetry.activeCallbackPump.events.push(line);
        }
        console.log(`[Client Probe] ${new Date().toISOString()} ${line}${trace ? ` stack=${trace}` : ""}`);
    };

    const runCallbacks = findExport("SteamAPI_RunCallbacks");
    safeAttach(runCallbacks, "SteamAPI_RunCallbacks", {
        onEnter: function() {
            const pump = {
                id: ++run20Telemetry.callbackPumpCount,
                startMs: Date.now(),
                events: []
            };
            this.pump = pump;
            run20Telemetry.activeCallbackPump = pump;
        },
        onLeave: function() {
            if (this.pump.events.length > 0) {
                console.log(`[Client Probe] ${new Date().toISOString()} SteamAPI_RunCallbacks pump=${this.pump.id} auth_events=${this.pump.events.length} duration_ms=${Date.now() - this.pump.startMs}`);
            }
            if (run20Telemetry.activeCallbackPump === this.pump) {
                run20Telemetry.activeCallbackPump = null;
            }
        }
    });

    const bGetCallback = findExport("Steam_BGetCallback");
    safeAttach(bGetCallback, "Steam_BGetCallback", {
        onEnter: function(args) {
            this.callbackMessage = args[1];
        },
        onLeave: function(retval) {
            if (retval.toInt32() === 0 || !this.callbackMessage || this.callbackMessage.isNull()) {
                return;
            }
            try {
                // CallbackMsg_t (x86): HSteamUser, callback id, payload ptr,
                // payload size.
                const callbackId = this.callbackMessage.add(4).readS32();
                if ((callbackId >= 100 && callbackId < 200) || callbackNames[callbackId]) {
                    const payload = this.callbackMessage.add(8).readPointer();
                    const payloadSize = this.callbackMessage.add(12).readS32();
                    recordCallbackDispatch("Steam_BGetCallback", callbackId, payload, payloadSize, "");
                }
            } catch (error) {
                console.log(`[Client Probe] ${new Date().toISOString()} Steam_BGetCallback parse_error=${error}`);
            }
        }
    });

    // FEAR 3's 124712-byte legacy steam_api.dll does not export
    // Steam_BGetCallback. Its two internal callback dispatchers receive a
    // CallbackMsg_t* as their second argument. Guard the version-specific
    // RVAs with opcode signatures before attaching, then parse the same x86
    // CallbackMsg_t layout used above: user, id, payload pointer, size.
    const matchesOpcodePrefix = function(address, expected) {
        try {
            const bytes = new Uint8Array(address.readByteArray(expected.length));
            for (let index = 0; index < expected.length; index++) {
                if (bytes[index] !== expected[index]) {
                    return false;
                }
            }
            return true;
        } catch (_) {
            return false;
        }
    };

    const attachLegacyCallbackDispatcher = function(rva, expectedPrefix, label) {
        const address = steamApi.base.add(rva);
        if (!matchesOpcodePrefix(address, expectedPrefix)) {
            console.log(`  [-] Skipping ${label}: opcode signature mismatch at ${address}`);
            return;
        }
        safeAttach(address, label, {
            onEnter: function(args) {
                const callbackMessage = args[1];
                if (!callbackMessage || callbackMessage.isNull()) {
                    return;
                }
                try {
                    const callbackId = callbackMessage.add(4).readS32();
                    const payload = callbackMessage.add(8).readPointer();
                    const payloadSize = callbackMessage.add(12).readS32();
                    if (((callbackId >= 100 && callbackId < 200) || callbackNames[callbackId]) &&
                        payloadSize >= 0 && payloadSize <= 4096) {
                        recordCallbackDispatch(label, callbackId, payload, payloadSize, stackTrace(this.context));
                    }
                } catch (error) {
                    console.log(`[Client Probe] ${new Date().toISOString()} ${label} parse_error=${error}`);
                }
            }
        });
    };

    attachLegacyCallbackDispatcher(
        0x1570,
        [0x83, 0xec, 0x10, 0x53],
        "LegacyCallbackDispatchNoTry"
    );
    attachLegacyCallbackDispatcher(
        0x13f0,
        [0x55, 0x8b, 0xec, 0x6a],
        "LegacyCallbackDispatchTryCatch"
    );

    // Also observe callback objects registered after attachment. This supplies
    // the FEAR 3 handler stack in addition to Steam_BGetCallback's raw result.
    const callbackObjects = {};
    const hookedCallbackHandlers = {};
    const hookCallbackObject = function(callbackObject, callbackId) {
        if (!callbackObject || callbackObject.isNull()) {
            return;
        }
        callbackObjects[callbackObject.toString()] = callbackId;
        if (!((callbackId >= 100 && callbackId < 200) || callbackNames[callbackId])) {
            return;
        }
        try {
            const callbackVtable = callbackObject.readPointer();
            for (let slot = 0; slot <= 1; slot++) {
                const handler = callbackVtable.add(slot * Process.pointerSize).readPointer();
                const key = handler.toString();
                if (hookedCallbackHandlers[key]) {
                    continue;
                }
                hookedCallbackHandlers[key] = true;
                safeAttach(handler, `Steam callback handler slot ${slot}`, {
                    onEnter: function(args) {
                        const objectKey = this.context.ecx.toString();
                        const activeId = callbackObjects[objectKey] || callbackId;
                        const payload = args[0];
                        let payloadSize = 0;
                        if (activeId === 143) {
                            payloadSize = 20;
                        } else if (activeId === 163) {
                            payloadSize = 8;
                        }
                        recordCallbackDispatch(`CCallbackBase::Run[${slot}]`, activeId, payload, payloadSize, stackTrace(this.context));
                    }
                });
            }
        } catch (error) {
            console.log(`[Client Probe] ${new Date().toISOString()} callback_object_hook_error id=${callbackId}: ${error}`);
        }
    };

    const registerCallback = findExport("SteamAPI_RegisterCallback");
    safeAttach(registerCallback, "SteamAPI_RegisterCallback", {
        onEnter: function(args) {
            const callbackObject = args[0];
            const callbackId = args[1].toInt32();
            hookCallbackObject(callbackObject, callbackId);
            if ((callbackId >= 100 && callbackId < 200) || callbackNames[callbackId]) {
                console.log(`[Client Probe] ${new Date().toISOString()} SteamAPI_RegisterCallback object=${callbackObject} callback=${callbackId}/${callbackNames[callbackId] || "UnknownSteamUserCallback"}`);
            }
        }
    });

    // Best-effort dialog tracing. FEAR 3 normally uses an in-game UI, but
    // these Windows text paths catch fallback dialogs and text presentation.
    // Static literal access monitoring covers the custom-UI path without
    // changing game memory.
    const relevantDialogText = function(text) {
        if (!text) {
            return false;
        }
        const normalized = text.toLowerCase();
        return normalized.indexOf("failed authentication") !== -1 ||
            normalized.indexOf("kicked by the host") !== -1 ||
            normalized.indexOf("connection lost") !== -1 ||
            normalized.indexOf("connection to the host") !== -1;
    };

    const readDialogString = function(address, wide) {
        if (!address || address.isNull()) {
            return "";
        }
        try {
            return wide ? address.readUtf16String() : address.readCString();
        } catch (_) {
            return "";
        }
    };

    const hookDialogTextApi = function(moduleName, apiName, textArgIndex, wide) {
        const address = findModuleExport(moduleName, apiName);
        safeAttach(address, apiName, {
            onEnter: function(args) {
                const text = readDialogString(args[textArgIndex], wide);
                if (relevantDialogText(text)) {
                    console.log(`[Client Probe] ${new Date().toISOString()} DialogText api=${apiName} text=${JSON.stringify(text)} stack=${stackTrace(this.context)}`);
                }
            }
        });
    };

    hookDialogTextApi("user32.dll", "MessageBoxA", 1, false);
    hookDialogTextApi("user32.dll", "MessageBoxW", 1, true);
    hookDialogTextApi("user32.dll", "SetWindowTextA", 1, false);
    hookDialogTextApi("user32.dll", "SetWindowTextW", 1, true);
    hookDialogTextApi("user32.dll", "DrawTextA", 1, false);
    hookDialogTextApi("user32.dll", "DrawTextW", 1, true);
    hookDialogTextApi("user32.dll", "TextOutA", 3, false);
    hookDialogTextApi("user32.dll", "TextOutW", 3, true);

    const dialogLiterals = [
        "Failed authentication!",
        "Kicked by the host",
        "Connection lost",
        "Connection to the host"
    ];
    const patternForText = function(text, wide) {
        const bytes = [];
        for (let index = 0; index < text.length; index++) {
            const code = text.charCodeAt(index);
            bytes.push((code & 0xff).toString(16).padStart(2, "0"));
            if (wide) {
                bytes.push(((code >>> 8) & 0xff).toString(16).padStart(2, "0"));
            }
        }
        return bytes.join(" ");
    };

    if (typeof MemoryAccessMonitor !== "undefined") {
        try {
            const mainModule = Process.mainModule;
            const scanRanges = mainModule.enumerateRanges("r--")
                .concat(mainModule.enumerateRanges("rw-"));
            const monitoredPagesByAddress = {};
            for (const text of dialogLiterals) {
                for (const wide of [false, true]) {
                    const pattern = patternForText(text, wide);
                    for (const range of scanRanges) {
                        const matches = Memory.scanSync(range.base, range.size, pattern);
                        for (const match of matches) {
                            const pageAddress = match.address.toUInt32() & ~(Process.pageSize - 1);
                            const pageKey = `0x${pageAddress.toString(16)}`;
                            if (!monitoredPagesByAddress[pageKey]) {
                                monitoredPagesByAddress[pageKey] = {
                                    base: ptr(pageAddress),
                                    size: Process.pageSize,
                                    labels: []
                                };
                            }
                            monitoredPagesByAddress[pageKey].labels.push(`${JSON.stringify(text)}/${wide ? "utf16" : "ascii"}@${match.address}`);
                        }
                    }
                }
            }
            const monitoredPages = Object.keys(monitoredPagesByAddress)
                .map(key => monitoredPagesByAddress[key]);
            if (monitoredPages.length > 0) {
                MemoryAccessMonitor.enable(monitoredPages.map(page => ({
                    base: page.base,
                    size: page.size
                })), {
                    onAccess: function(details) {
                        const page = monitoredPages[details.rangeIndex];
                        const trace = details.context ? stackTrace(details.context) : DebugSymbol.fromAddress(details.from).toString();
                        console.log(`[Client Probe] ${new Date().toISOString()} DialogLiteralAccess labels=${page.labels.join("|")} operation=${details.operation} from=${details.from} address=${details.address} stack=${trace}`);
                    }
                });
                console.log(`  [+] Monitoring ${monitoredPages.length} main-module page(s) containing dialog literals`);
            } else {
                console.log("  [-] No target dialog literals found in readable main-module ranges");
            }
        } catch (error) {
            console.log(`  [-] Dialog literal monitor unavailable: ${error}`);
        }
    }
} else {
    console.log("[CrossLab Probe] steam_api.dll not yet loaded; waiting for module load event.");
}
