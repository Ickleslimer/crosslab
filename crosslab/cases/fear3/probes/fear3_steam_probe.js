/**
 * FEAR 3 Steam P2P Diagnostic Probe (Frida Hook Script)
 * Intercepts packet I/O, legacy P2P session lifecycle, and auth-ticket calls.
 * 
 * Usage:
 *   frida -n "F.E.A.R. 3.exe" -l fear3_steam_probe.js
 */

console.log("[CrossLab Probe] Initializing Steam networking hooks in Fear3.exe...");

const steamApi = Process.findModuleByName("steam_api.dll") || Process.findModuleByName("steam_api64.dll");

if (steamApi) {
    console.log(`[CrossLab Probe] Found steam_api at ${steamApi.base}`);

    // Run 19 intervention: suppress only the exact sixteen-byte channel-4101
    // frame that immediately triggered client-side teardown in clean Run 18.
    // The five-byte 0x64 frame and later fifteen-byte 0x50 frame must pass
    // unchanged so this remains a single-variable causal test. Do not arm the
    // filter during lobby negotiation; channel 4098 traffic is our observable
    // boundary that the replicated gameplay stream has started.
    const run19Filter = {
        enabled: true,
        armed: false,
        trigger: [
            0x50, 0x00, 0x61, 0x64, 0x80, 0x24, 0x01, 0x00,
            0x05, 0x00, 0x00, 0x80, 0x80, 0x00, 0x00, 0x00
        ]
    };

    const matchesBytes = function(buffer, expected) {
        if (!buffer || buffer.byteLength !== expected.length) {
            return false;
        }
        const bytes = new Uint8Array(buffer);
        for (let index = 0; index < expected.length; index++) {
            if (bytes[index] !== expected[index]) {
                return false;
            }
        }
        return true;
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
                let payloadPreview = "";
                if (this.channel === 4101 || this.cubData <= 32) {
                    try {
                        const bytes = this.pubData.readByteArray(Math.min(this.cubData, 32));
                        const hex = Array.from(new Uint8Array(bytes)).map(b => b.toString(16).padStart(2, '0')).join(' ');
                        payloadPreview = ` hex=[${hex}]`;
                    } catch(e) {}
                }
                console.log(`[Client Probe] ${new Date().toISOString()} SendP2PPacket #${this.pktId} (${this.cubData} bytes, channel=${this.channel})${payloadPreview} -> bool: ${success ? "true" : "false"}`);
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

                    if (run19Filter.enabled && !run19Filter.armed &&
                        this.channel === 4098 && messageSize > 0) {
                        run19Filter.armed = true;
                        console.log(`[Client Probe] ${new Date().toISOString()} Run19Filter ARMED after first channel=4098 gameplay packet`);
                    }

                    if (run19Filter.enabled && run19Filter.armed &&
                        this.channel === 4101 && messageSize === run19Filter.trigger.length) {
                        try {
                            const candidate = this.pubDest.readByteArray(messageSize);
                            if (matchesBytes(candidate, run19Filter.trigger)) {
                                recvPacketCounter++;
                                console.log(`[Client Probe] ${new Date().toISOString()} Run19Filter DROPPED ReadP2PPacket #${recvPacketCounter} (16 bytes, channel=4101) hex=[50 00 61 64 80 24 01 00 05 00 00 80 80 00 00 00] -> bool: false`);
                                if (this.pcubMsgSize && !this.pcubMsgSize.isNull()) {
                                    this.pcubMsgSize.writeU32(0);
                                }
                                // Steam has already dequeued the packet. Returning false
                                // prevents FEAR 3 from processing this one frame.
                                retval.replace(0);
                                return;
                            }
                        } catch (error) {
                            console.log(`[Client Probe] ${new Date().toISOString()} Run19Filter ERROR: ${error}`);
                        }
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
                    console.log(`[Client Probe] ${new Date().toISOString()} ReadP2PPacket #${recvPacketCounter} (${messageSize} bytes, channel=${this.channel})${payloadPreview} -> bool: true`);
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
                console.log(`[Client Probe] ${new Date().toISOString()} CloseP2PSessionWithUser remote=${remote} stack=${stackTrace(this.context)}`);
            }
        });

        Interceptor.attach(sessionSlots[5], {
            onEnter: function(args) {
                const remote = steamIdKey(args[0].toUInt32(), args[1].toUInt32());
                const channel = args[2].toInt32();
                console.log(`[Client Probe] ${new Date().toISOString()} CloseP2PChannelWithUser remote=${remote} channel=${channel} stack=${stackTrace(this.context)}`);
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
                    console.log(`[Client Probe] ${new Date().toISOString()} GetAuthSessionTicket handle=${retval.toUInt32()} size=${size} stack=${this.trace}`);
                }
            });

            Interceptor.attach(authSlots[14], {
                onEnter: function(args) {
                    this.ticketBytes = args[1].toUInt32();
                    this.remote = steamIdKey(args[2].toUInt32(), args[3].toUInt32());
                    this.trace = stackTrace(this.context);
                },
                onLeave: function(retval) {
                    console.log(`[Client Probe] ${new Date().toISOString()} BeginAuthSession remote=${this.remote} ticketBytes=${this.ticketBytes} result=${retval.toInt32()} stack=${this.trace}`);
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
                    console.log(`[Client Probe] ${new Date().toISOString()} CancelAuthTicket handle=${args[0].toUInt32()} stack=${stackTrace(this.context)}`);
                }
            });

            console.log(`  [+] Attached legacy auth hooks: GetTicket=${authSlots[13]} Begin=${authSlots[14]} End=${authSlots[15]} Cancel=${authSlots[16]}`);
        }
    }
} else {
    console.log("[CrossLab Probe] steam_api.dll not yet loaded; waiting for module load event.");
}
