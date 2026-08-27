/**
 * FEAR 3 Steam P2P Diagnostic Probe (Frida Hook Script)
 * Intercepts SendP2PPacket, ReadP2PPacket, and SteamNetworkingSockets callbacks.
 * 
 * Usage:
 *   frida -n Fear3.exe -l fear3_steam_probe.js
 */

console.log("[CrossLab Probe] Initializing Steam networking hooks in Fear3.exe...");

const steamApi = Process.findModuleByName("steam_api.dll") || Process.findModuleByName("steam_api64.dll");

if (steamApi) {
    console.log(`[CrossLab Probe] Found steam_api at ${steamApi.base}`);

    // Hook SteamNetworking005 / ISteamNetworking::SendP2PPacket
    const sendP2P = Module.findExportByName(steamApi.name, "SteamAPI_ISteamNetworking_SendP2PPacket");
    if (sendP2P) {
        let sentPacketCounter = 0;
        Interceptor.attach(sendP2P, {
            onEnter: function(args) {
                this.steamIDRemote = args[1];
                this.pubData = args[2];
                this.cubData = args[3].toInt32();
                this.eP2PSendType = args[4].toInt32();
                sentPacketCounter++;
                this.pktId = sentPacketCounter;
            },
            onLeave: function(retval) {
                const success = retval.toInt32() !== 0;
                console.log(`[Client Probe] SendP2PPacket #${this.pktId} (${this.cubData} bytes) -> return: ${success ? "OK" : "FAIL"}`);
            }
        });
        console.log("  [+] Attached hook to SteamAPI_ISteamNetworking_SendP2PPacket");
    }

    // Hook SteamNetworking005 / ISteamNetworking::ReadP2PPacket
    const readP2P = Module.findExportByName(steamApi.name, "SteamAPI_ISteamNetworking_ReadP2PPacket");
    if (readP2P) {
        let recvPacketCounter = 0;
        Interceptor.attach(readP2P, {
            onEnter: function(args) {
                this.pubDest = args[1];
                this.cubDest = args[2].toInt32();
                this.pcubMsgSize = args[3];
                this.psteamIDRemote = args[4];
            },
            onLeave: function(retval) {
                const hasPacket = retval.toInt32() !== 0;
                if (hasPacket) {
                    recvPacketCounter++;
                    console.log(`[Host Probe] ReadP2PPacket #${recvPacketCounter} received.`);
                }
            }
        });
        console.log("  [+] Attached hook to SteamAPI_ISteamNetworking_ReadP2PPacket");
    }
} else {
    console.log("[CrossLab Probe] steam_api.dll not yet loaded; waiting for module load event.");
}
