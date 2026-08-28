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

    const stackTrace = function(context) {
        try {
            return Thread.backtrace(context, Backtracer.ACCURATE)
                .map(DebugSymbol.fromAddress)
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
                const remote = steamIdKey(args[0].toUInt32(), args[1].toUInt32());
                const channel = args[2].toInt32();
                console.log(`[Client Probe] ${new Date().toISOString()} CloseP2PChannelWithUser remote=${remote} channel=${channel} ${lastSentSummary()} stack=${stackTrace(this.context)}`);
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
