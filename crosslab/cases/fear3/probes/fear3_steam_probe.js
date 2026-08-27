/**
 * FEAR 3 Steam P2P Diagnostic Probe (Frida Hook Script)
 * Intercepts SendP2PPacket, ReadP2PPacket, and SteamNetworkingSockets callbacks.
 * 
 * Usage:
 *   frida -n "F.E.A.R. 3.exe" -l fear3_steam_probe.js
 */

console.log("[CrossLab Probe] Initializing Steam networking hooks in Fear3.exe...");

const steamApi = Process.findModuleByName("steam_api.dll") || Process.findModuleByName("steam_api64.dll");

if (steamApi) {
    console.log(`[CrossLab Probe] Found steam_api at ${steamApi.base}`);

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

    // Newer Steamworks SDKs expose flat wrapper functions. FEAR 3 ships an
    // older 32-bit steam_api.dll that only exports SteamNetworking(), so fall
    // back to ISteamNetworking's vtable (Send=slot 0, Read=slot 2).
    let legacyVtable = false;
    let sendP2P = findExport("SteamAPI_ISteamNetworking_SendP2PPacket");
    let readP2P = findExport("SteamAPI_ISteamNetworking_ReadP2PPacket");

    if (!sendP2P || !readP2P) {
        const networkingFactory = findExport("SteamNetworking");
        if (networkingFactory) {
            const getNetworking = new NativeFunction(networkingFactory, "pointer", []);
            const networking = getNetworking();
            if (!networking.isNull()) {
                const vtable = networking.readPointer();
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
                console.log(`[Client Probe] ${new Date().toISOString()} SendP2PPacket #${this.pktId} (${this.cubData} bytes, channel=${this.channel}) -> bool: ${success ? "true" : "false"}`);
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
                    recvPacketCounter++;
                    let messageSize = 0;
                    if (this.pcubMsgSize && !this.pcubMsgSize.isNull()) {
                        messageSize = this.pcubMsgSize.readU32();
                    }
                    console.log(`[Client Probe] ${new Date().toISOString()} ReadP2PPacket #${recvPacketCounter} (${messageSize} bytes, channel=${this.channel}) -> bool: true`);
                }
            }
        });
        console.log(`  [+] Attached ReadP2PPacket hook at ${readP2P}`);
    } else {
        console.log("  [-] Could not resolve ReadP2PPacket");
    }
} else {
    console.log("[CrossLab Probe] steam_api.dll not yet loaded; waiting for module load event.");
}
