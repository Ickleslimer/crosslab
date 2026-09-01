import sqlite3
import json
from crosslab.engine.session import InvestigationSession
from crosslab.protocol.models import RunRecord, Observation, utc_now_iso
from crosslab.protocol.actions import RunOutcome

def backfill(db_path='D:/crosslab/crosslab_fear3-debug.db', session_id='fear3-debug'):
    session = InvestigationSession(session_id=session_id, db_path=db_path)
    
    # Load observations to associate with runs
    all_obs = session.storage.get_observations()
    obs_by_run = {}
    for o in all_obs:
        obs_by_run.setdefault(o.run_id, []).append(o)

    runs_data = [
        {
            'run_id': 14,
            'build': 'baseline-telemetry-fdcdce9',
            'hypothesis_id': 'hyp_2829f750',
            'hypothesis_title': 'Host receive silence watchdog triggers disconnect',
            'start_time': '2026-08-27T23:51:51.435Z',
            'end_time': '2026-08-27T23:54:26.107Z',
            'outcome': RunOutcome.REPRODUCED,
            'result_summary': 'Sudden bidirectional P2P silence at ~101.3s from first send during cinematic/gameplay. Disproved asymmetric send hypothesis.',
            'host': {'last_sent_packet': 520, 'disconnect_reason': 'connection_lost', 'silence_onset_elapsed_sec': 101.3},
            'client': {'first_sent_packet': 1, 'last_read_packet': 1176, 'last_sent_packet': 644, 'send_failures': 0, 'disconnect_reported': True},
        },
        {
            'run_id': 15,
            'build': 'baseline-cinematic-skip',
            'hypothesis_id': 'hyp_68e144e5',
            'hypothesis_title': 'Intro cinematic playback causes synchronous thread blocking',
            'start_time': '2026-08-28T00:00:03.288Z',
            'end_time': '2026-08-28T00:02:21.408Z',
            'outcome': RunOutcome.REPRODUCED,
            'result_summary': 'Cinematic skipped immediately, but disconnect still reproduced at ~103.5s of elapsed gameplay. Disproved cinematic trigger hypothesis.',
            'host': {'last_sent_packet': 940, 'disconnect_reason': 'connection_lost', 'silence_onset_elapsed_sec': 103.5},
            'client': {'first_sent_packet': 645, 'last_read_packet': 2519, 'last_sent_packet': 1337, 'send_failures': 0, 'disconnect_reported': True},
        },
        {
            'run_id': 16,
            'build': 'commit-2aa2941-lifecycle',
            'hypothesis_id': 'hyp_7b891a22',
            'hypothesis_title': 'Client actively initiates teardown via CloseP2PChannel',
            'start_time': '2026-08-28T00:09:31.994Z',
            'end_time': '2026-08-28T00:15:47.935Z',
            'outcome': RunOutcome.REPRODUCED,
            'result_summary': 'Proved Client initiates teardown sequence: Channel 4100 closed first at 00:15:46.695Z, then Channel 4101 at 00:15:46.862Z, then full P2P session close.',
            'host': {'close_p2p_session_time': '2026-08-28T00:15:47.935Z', 'disconnect_reason': 'session_closed_by_peer'},
            'client': {'close_channel_4100_time': '2026-08-28T00:15:46.695Z', 'close_channel_4101_time': '2026-08-28T00:15:46.862Z', 'close_session_time': '2026-08-28T00:15:46.870Z', 'last_read_packet': 3152, 'last_sent_packet': 1682},
        },
        {
            'run_id': 17,
            'build': 'commit-b7fb9fd-payload-hex',
            'hypothesis_id': 'hyp_7b891a22',
            'hypothesis_title': 'Spurious control burst on channel 4101 triggers client teardown',
            'start_time': '2026-08-28T00:24:21.165Z',
            'end_time': '2026-08-28T00:28:45.000Z',
            'outcome': RunOutcome.REPRODUCED,
            'result_summary': 'Discovered the 3-frame post-match control burst on Channel 4101 immediately preceding client teardown: 5B [64 01...], 16B [50 00 61...], 15B [50 00 5a...].',
            'host': {'burst_sent_channel_4101': True, 'disconnect_reason': 'connection_lost'},
            'client': {'burst_received_channel_4101': True, 'last_read_packet': 3820, 'last_sent_packet': 1950},
        },
        {
            'run_id': 18,
            'build': 'commit-bfddb91-drop-5b',
            'hypothesis_id': 'hyp_cdd7276c',
            'hypothesis_title': '5-byte frame [64 01 00 00 00] is the sole teardown trigger',
            'start_time': '2026-08-28T00:32:11.891Z',
            'end_time': '2026-08-28T00:43:44.432Z',
            'outcome': RunOutcome.REPRODUCED,
            'result_summary': 'Dropped 5B frame at 00:43:06.861Z. Client read subsequent 16B frame and closed ch4101 within 1ms. Proved 5B frame alone is not sufficient to prevent teardown.',
            'host': {'filter_armed': True, 'filter_dropped_packets': 0},
            'client': {'filter_dropped_5b_time': '2026-08-28T00:43:06.861Z', 'read_16b_time': '2026-08-28T00:43:06.863Z', 'close_channel_4101_time': '2026-08-28T00:43:06.864Z'},
        },
        {
            'run_id': 19,
            'build': 'commit-61697ea-drop-16b',
            'hypothesis_id': 'hyp_5426b358',
            'hypothesis_title': '16-byte frame [50 00 61 64...] triggers Steam Auth revalidation',
            'start_time': '2026-08-28T00:52:03.528Z',
            'end_time': '2026-08-28T00:56:13.855Z',
            'outcome': RunOutcome.REPRODUCED,
            'result_summary': 'Dropping 16B frame triggered explicit in-game error modal: Failed authentication! Unmasked the Steam Auth Session ticket revalidation state machine.',
            'host': {'burst_sent_time': '2026-08-28T00:55:38.156Z', 'disconnect_reason': 'auth_failure'},
            'client': {'filter_dropped_16b_time': '2026-08-28T00:55:39.109Z', 'in_game_dialog': 'Failed authentication!', 'close_channel_4101_time': '2026-08-28T00:55:39.114Z'},
        },
        {
            'run_id': 20,
            'build': 'commit-999ea60-auth-trace',
            'hypothesis_id': 'hyp_5426b358',
            'hypothesis_title': 'Steam auth ticket recheck callback fails in modern Steam environment',
            'start_time': '2026-08-28T01:35:41.066Z',
            'end_time': '2026-08-28T02:00:00.000Z',
            'outcome': RunOutcome.REPRODUCED,
            'result_summary': 'Passive tracing of ISteamUser auth calls during natural disconnect. Verified Steam auth ticket recheck behavior.',
            'host': {'auth_hooks_installed': True, 'disconnect_reason': 'connection_lost'},
            'client': {'auth_hooks_installed': True, 'disconnect_reported': True},
        },
        {
            'run_id': 21,
            'build': 'commit-c29be70-stalker-callout',
            'hypothesis_id': 'hyp_5426b358',
            'hypothesis_title': 'Authoritative caller RVA via Frida Stalker instruction callouts',
            'start_time': '2026-08-28T03:20:52.703Z',
            'end_time': '2026-08-28T03:28:36.655Z',
            'outcome': RunOutcome.CRASH,
            'result_summary': 'Client experienced premature fast-fail crash (0xc0000409 BEX in KERNELBASE.dll) ~81.7s into active gameplay. Run aborted and WER Report.wer audit performed.',
            'host': {'status': 'passive_observation_active'},
            'client': {'crash_time': '2026-08-28T03:27:11.636Z', 'exception_code': '0xc0000409', 'fault_module': 'KERNELBASE.dll', 'wer_report_sha256': 'e8fdae613aca56881687a858f88cb6c54249c7bf802032b7bc586f6b07aa193d'},
        },
    ]

    for rd in runs_data:
        rid = rd['run_id']
        rd_obs = obs_by_run.get(rid, [])
        run_record = RunRecord(
            run_id=rid,
            session_id=session_id,
            hypothesis_id=rd.get('hypothesis_id'),
            hypothesis_title=rd.get('hypothesis_title'),
            build=rd.get('build', 'default-build'),
            participants=['agent-host', 'agent-client', 'human-host', 'human-client'],
            start_time=rd.get('start_time'),
            end_time=rd.get('end_time'),
            outcome=rd.get('outcome', RunOutcome.PENDING),
            result_summary=rd.get('result_summary'),
            host=rd.get('host', {}),
            client=rd.get('client', {}),
            observations=rd_obs,
            created_at=rd.get('start_time', utc_now_iso())
        )
        saved = session.record_run(run_record)
        print(f'Successfully ingested Run {saved.run_id} ({saved.outcome.value}): {saved.result_summary[:80]}...')

if __name__ == '__main__':
    backfill()
