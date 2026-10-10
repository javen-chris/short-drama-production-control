"""Fixed Terra dispatch for a frozen request; client evidence is not server proof."""
from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .final_submission import QA_MODEL, digest_packet, validate_packet


def review(packet_path, output_directory, *, executable=None, runner=subprocess.run):
    packet_path = Path(packet_path).resolve()
    packet = validate_packet(json.loads(packet_path.read_text(encoding='utf-8')))
    out = Path(output_directory).resolve()
    out.mkdir(parents=True, exist_ok=True)
    invocation_path = out / 'qa_invocation.json'
    qa_path = out / 'final_packet_QA.json'
    events_path = out / 'qa_client_events.jsonl'
    if any(p.exists() for p in (invocation_path, qa_path, events_path)):
        raise ValueError('QA_OUTPUT_VERSION_EXISTS: preserve old review, use a new directory')
    executable = executable or shutil.which('codex.cmd') or shutil.which('codex')
    if not executable:
        raise ValueError('QA_INVOCATION_EXCEPTION: Codex executable unavailable')
    record = {'requested_model': QA_MODEL, 'packet_path': str(packet_path),
              'packet_sha256': digest_packet(packet), 'started_at': datetime.now(timezone.utc).isoformat(),
              'status': 'STARTED', 'session_id': None, 'evidence_type': 'client_execution_record',
              'identity': 'client_selected_model_not_server_authenticated'}
    def save():
        invocation_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    save()
    prompt = f'''Review ONLY this frozen final submission packet: {packet_path}
and the asset snapshots listed in that packet. Do not inspect provider templates,
live default nodes, or example audio. Compare settings to payload, duration,
aspect/resolution, prompt, upload image bindings, identity, and disabled external
audio. The caller selected {QA_MODEL}; client dispatch evidence is recorded by
the caller. Do not invent a cryptographic server identity requirement as a
content finding. Assess content only; execution exceptions are separate.
Packet hash contract: reviewed_packet_sha256 is SHA-256 of the canonical
PARSED JSON object, using this exact Python computation:
packet = json.loads(Path(packet_path).read_text(encoding='utf-8'))
canonical_bytes = json.dumps(packet, ensure_ascii=False, sort_keys=True,
    separators=(',', ':'), allow_nan=False).encode('utf-8')
reviewed_packet_sha256 = hashlib.sha256(canonical_bytes).hexdigest()
Hash the whole parsed packet, not just payload. The raw file byte hash is NOT
this field: indentation, spaces, line endings, and JSON object key order in the
source file are not part of the canonical hash. Asset sha256 fields separately
refer to the raw image bytes. Do not report a content FAIL because the raw JSON
file hash differs from the canonical packet hash. A change to parsed packet
content or bound image bytes still invalidates the prior QA and blocks submit.
Return ONLY JSON: overall PASS/FAIL/UNCERTAIN, qa_model "{QA_MODEL}",
reviewed_packet_sha256 "{digest_packet(packet)}", checks (nonempty list of
objects with name, status PASS/FAIL/UNCERTAIN, reason). Do not write files.
'''
    command = [str(executable), 'exec', '--model', QA_MODEL, '--json', '--skip-git-repo-check',
               '--sandbox', 'read-only', '--output-last-message', str(qa_path), '-']
    record['command'] = command
    save()
    try:
        result = runner(command, input=prompt, text=True, encoding='utf-8',
                        capture_output=True, cwd=str(packet_path.parent), timeout=600)
        events_path.write_text(result.stdout, encoding='utf-8')
        for line in result.stdout.splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get('type') == 'thread.started':
                record['session_id'] = event.get('thread_id')
        record['exit_code'] = result.returncode
        if result.returncode or not record['session_id'] or not qa_path.is_file():
            raise ValueError('QA_INVOCATION_EXCEPTION: failed client run or missing session/report')
        qa = json.loads(qa_path.read_text(encoding='utf-8'))
        if qa.get('qa_model') != QA_MODEL or qa.get('reviewed_packet_sha256') != record['packet_sha256']:
            raise ValueError('QA_INVOCATION_EXCEPTION: report route/packet mismatch')
        if qa.get('overall') not in {'PASS', 'FAIL', 'UNCERTAIN'} or not qa.get('checks'):
            raise ValueError('QA_INVOCATION_EXCEPTION: invalid content report')
        if digest_packet(json.loads(packet_path.read_text(encoding='utf-8'))) != record['packet_sha256']:
            raise ValueError('QA_INVOCATION_EXCEPTION: packet changed during review')
        validate_packet(packet)
        record['status'] = 'COMPLETED'
        record['content_verdict'] = qa['overall']
        record['report_sha256'] = digest_packet(qa)
    except Exception as exc:
        record['status'] = 'EXECUTION_EXCEPTION'
        record['error'] = str(exc)
        raise
    finally:
        record['completed_at'] = datetime.now(timezone.utc).isoformat()
        save()
    return record
