"""Freeze the exact provider request before QA; submit only that reviewed request."""
from pathlib import Path
import hashlib
import json
import shutil
from datetime import datetime, timezone

QA_MODEL = 'gpt-5.6-terra'

def digest_file(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

def digest_packet(packet):
    return hashlib.sha256(json.dumps(packet, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()

def resolve_asset(path, expected_hash, roots):
    """Identity is exact bytes, never filename or visual similarity. Skip symlinks."""
    source = Path(path)
    allowed = [Path(r).resolve() for r in roots]
    def inside(candidate):
        return not candidate.is_symlink() and any(candidate.resolve().is_relative_to(r) for r in allowed)
    if source.is_file() and inside(source) and digest_file(source) == expected_hash:
        return source
    for root in roots:
        root = Path(root)
        if not root.is_dir():
            continue
        for candidate in sorted(root.rglob('*'), key=lambda x: str(x).casefold()):
            if not candidate.is_file() or not inside(candidate):
                continue
            try:
                if digest_file(candidate) == expected_hash:
                    return candidate
            except OSError:
                continue
    raise ValueError(f'ASSET_CONTENT_NOT_FOUND: {expected_hash}; select a new version explicitly')

def freeze_assets(manifest, directory, roots):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    result = []
    for entry in manifest:
        expected = entry['sha256'].lower()
        suffix = Path(entry['path']).suffix
        target = directory / (expected + suffix)
        if target.exists():
            if digest_file(target) != expected:
                raise ValueError('SNAPSHOT_CHANGED: ' + str(target))
            source = Path(entry.get('source_path', entry['path']))
            observed = digest_file(source) if source.is_file() else None
            if observed != expected:
                with (directory / 'snapshot_recovery.jsonl').open('a', encoding='utf-8') as log:
                    log.write(json.dumps({'at': datetime.now(timezone.utc).isoformat(),
                        'source': str(source), 'snapshot': str(target), 'sha256': expected,
                        'source_observed_sha256': observed, 'action': 'keep_confirmed_snapshot'}, ensure_ascii=False) + '\n')
        else:
            source = resolve_asset(entry['path'], expected, roots)
            if digest_file(source) != expected:
                raise ValueError('SOURCE_CHANGED_BEFORE_COPY')
            temporary = target.with_suffix(target.suffix + '.partial')
            shutil.copyfile(source, temporary)
            if digest_file(temporary) != expected or digest_file(source) != expected:
                temporary.unlink()
                raise ValueError('SOURCE_CHANGED_DURING_COPY')
            temporary.rename(target)
            with (directory / 'snapshot_recovery.jsonl').open('a', encoding='utf-8') as log:
                log.write(json.dumps({'at': datetime.now(timezone.utc).isoformat(),
                    'source': str(source), 'requested_path': entry['path'], 'snapshot': str(target),
                    'sha256': expected, 'recovered': str(source) != str(entry['path'])}, ensure_ascii=False) + '\n')
        result.append({**entry, 'source_path': entry.get('source_path', entry['path']), 'path': str(target), 'sha256': expected})
    return result

def validate_packet(packet):
    if packet.get('schema') != 'rh-final-submission/v1':
        raise ValueError('Only a compiled final submission packet is accepted')
    if packet.get('qa_model') != QA_MODEL:
        raise ValueError('Incorrect QA route')
    payload = packet['payload']
    if not (payload.get('workflowId') or payload.get('webappId')) or not payload.get('instanceType'):
        raise ValueError('Provider workflowId/webappId and instanceType must be frozen in payload')
    def no_secrets(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key.lower() in {'apikey', 'api_key', 'authorization', 'access_token'}:
                    raise ValueError('Secret field forbidden in frozen packet')
                no_secrets(item)
        elif isinstance(value, list):
            for item in value:
                no_secrets(item)
    no_secrets(packet)
    nodes = payload['nodeInfoList']
    values = {(str(n['nodeId']), n['fieldName']): n['fieldValue'] for n in nodes}
    if len(values) != len(nodes):
        raise ValueError('Duplicate node fields')
    settings = packet['settings']
    for field, key in [('prompt', ('25','value')), ('duration', ('28','value')),
                       ('megapixels', ('26','megapixels')), ('aspect_ratio', ('26','aspect_ratio'))]:
        if str(values.get(key)) != str(settings[field]):
            raise ValueError('Final node/settings mismatch: ' + field)
    if not packet['assets']:
        raise ValueError('No bound reference snapshots')
    for asset in packet['assets']:
        if digest_file(asset['path']) != asset['sha256']:
            raise ValueError('Asset snapshot changed')
        if values.get((str(asset['node_id']), 'image')) != asset['uploaded_filename']:
            raise ValueError('Image upload binding mismatch')
        if not asset['uploaded_filename'] or asset['uploaded_filename'] == 'None':
            raise ValueError('Unresolved image binding')
    for node_id in packet['disabled_audio_nodes']:
        if values.get((str(node_id), 'audio')) != 'None':
            raise ValueError('External audio input not disabled')
    return packet

def load_approved_packet(packet_path, qa_path):
    packet = json.loads(Path(packet_path).read_text(encoding='utf-8'))
    qa = json.loads(Path(qa_path).read_text(encoding='utf-8'))
    if qa.get('overall') != 'PASS' or qa.get('qa_model') != QA_MODEL:
        raise ValueError('Independent routed QA PASS required')
    if not qa.get('checks') or any(item.get('status') != 'PASS' for item in qa.get('checks', [])):
        raise ValueError('Unresolved QA findings')
    if qa.get('reviewed_packet_sha256') != digest_packet(packet):
        raise ValueError('QA_PACKET_HASH_MISMATCH: review the changed packet')
    return validate_packet(packet)


def validate_invocation(invocation, packet, qa):
    """Validate client dispatch facts, without inventing server identity proof."""
    if invocation.get('requested_model') != QA_MODEL or invocation.get('status') != 'COMPLETED':
        raise ValueError('QA_INVOCATION_EXCEPTION: wrong route or incomplete invocation')
    if not invocation.get('started_at') or not invocation.get('session_id') or not invocation.get('completed_at'):
        raise ValueError('QA_INVOCATION_EXCEPTION: start/session/completion record required')
    if invocation.get('packet_sha256') != digest_packet(packet):
        raise ValueError('QA_INVOCATION_PACKET_MISMATCH')
    if invocation.get('report_sha256') != digest_packet(qa):
        raise ValueError('QA_INVOCATION_REPORT_MISMATCH')
    if invocation.get('evidence_type') != 'client_execution_record':
        raise ValueError('QA_INVOCATION_EXCEPTION: label client execution evidence honestly')
    return invocation


def bind_packet(project_root, run_id, packet_path):
    """Bind the completed upload request before QA, preserving prior versions."""
    from . import run_index, run_state
    root = Path(project_root)
    path = run_index.run_path(root, run_id)
    state = run_state.read_task(path)
    contract = state['execution_contract']
    if contract.get('selected_provider') != 'runninghub' or contract.get('current_step_id') not in {'S08', 'S09', 'A01'}:
        raise ValueError('FINAL_PACKET_BIND_STAGE_INVALID')
    if contract.get('provider_task_id') or contract.get('submission_attempts_used', 0):
        raise ValueError('FINAL_PACKET_ALREADY_CONSUMED')
    packet = validate_packet(json.loads((root / packet_path).read_text(encoding='utf-8')))
    if contract.get('execution_model') == QA_MODEL:
        raise ValueError('SELF_QA_VIOLATION: final packet requires independent Terra')
    record = {'packet_path': str(packet_path), 'packet_sha256': digest_packet(packet),
              'bound_at': datetime.now(timezone.utc).isoformat()}
    contract['final_submission'] = record
    contract['qa_model'] = QA_MODEL
    contract['final_packet_qa_required'] = True
    state.setdefault('final_submission_versions', []).append(record.copy())
    run_state.write_task(path, state)
    return record


def verify_bound_packet(root, contract, *, require_qa=True):
    binding = contract.get('final_submission') or {}
    if not binding.get('packet_path'):
        raise ValueError('FINAL_PACKET_REQUIRED: compile and bind the exact uploaded request before QA')
    packet_path = Path(root) / binding['packet_path']
    packet = validate_packet(json.loads(packet_path.read_text(encoding='utf-8')))
    if digest_packet(packet) != binding['packet_sha256']:
        raise ValueError('FINAL_PACKET_CHANGED: rebind a new version and re-review')
    if require_qa:
        for rel, expected in binding.get('reviewed_protocol_hashes', {}).items():
            if digest_file(Path(contract['protocol_root']) / rel) != expected:
                raise ValueError('FINAL_PACKET_QA_RULES_CHANGED: ' + rel)
        qa_path = Path(root) / binding['qa_path']
        load_approved_packet(packet_path, qa_path)
        qa = json.loads(qa_path.read_text(encoding='utf-8'))
        invocation = json.loads((Path(root) / binding['invocation_path']).read_text(encoding='utf-8'))
        validate_invocation(invocation, packet, qa)
    return packet


def submit_bound_packet(project_root, run_id, send):
    """Use the reviewed payload verbatim. send is the selected provider transport.

    Reserve once BEFORE network I/O; timeout/error never clears the consumed
    attempt. The transport must return sanitized task_id and status facts.
    """
    from . import run_index, run_state, protocol_versions
    from .progress import append_event
    root = Path(project_root)
    path = run_index.run_path(root, run_id)
    lock = path.with_suffix('.submit.lock')
    with lock.open('x', encoding='utf-8') as handle:
        handle.write(datetime.now(timezone.utc).isoformat())
    try:
        state = run_state.read_task(path)
        contract = state['execution_contract']
        if protocol_versions.check_current(contract):
            raise ValueError('PROTOCOL_SCOPE_CHANGED')
        if (contract.get('current_step_id') != 'S11' or contract.get('current_owner') != 'executor'
                or contract.get('selected_provider') != 'runninghub'):
            raise ValueError('FINAL_SUBMIT_STAGE_INVALID')
        auth = contract.get('submission_authorization') or {}
        if (not contract.get('provider_authorized') or auth.get('provider') != 'runninghub'
                or auth.get('run_id') != run_id or auth.get('scope') != 'single_video_submission'
                or auth.get('contract_id') != contract.get('contract_id') or auth.get('max_submissions') != 1
                or auth not in state.get('submission_authorizations', [])
                or digest_file(root / auth['evidence']) != auth.get('evidence_sha256')):
            raise ValueError('VIDEO_SUBMISSION_NOT_AUTHORIZED')
        if contract.get('provider_task_id') or contract.get('submission_count', 0) or contract.get('submission_attempts_used', 0):
            raise ValueError('SUBMISSION_ALREADY_CONSUMED: query existing task; never retry')
        attestation = state.get('protocol_attestation') or {}
        if attestation.get('status') != 'PASS' or attestation.get('scope_gate') != 'G6':
            raise ValueError('PROTOCOL_ATTESTATION_REQUIRED: current G6 proof missing')
        packet = verify_bound_packet(root, contract)
        receipt_path = root / 'workflow' / 'submission_receipts' / (run_id + '.json')
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        if receipt_path.exists():
            raise ValueError('SUBMISSION_RECEIPT_ALREADY_EXISTS')
        contract['submission_attempts_used'] = 1
        contract['submitted_packet_sha256'] = digest_packet(packet)
        run_state.write_task(path, state)
        # No template fetch, upload, node reconstruction, or prompt concatenation.
        response = send(json.loads(json.dumps(packet['payload'], ensure_ascii=False)))
        if not response.get('task_id') or not response.get('status'):
            raise ValueError('SUBMISSION_RESPONSE_UNVERIFIED: consumed attempt retained')
        receipt_path.write_text(json.dumps({'task_id': response['task_id'], 'status': response['status'],
            'submitted_packet_sha256': digest_packet(packet)}, ensure_ascii=False, indent=2), encoding='utf-8')
        refs = next(s['protocol_refs'] for s in contract['steps'] if s['id'] == 'S11')
        return append_event(root, run_id, step='S11', gate='G6', role='executor',
            source_adapter='runninghub', provider_task_id=response['task_id'], provider_status=response['status'],
            outcome='TASK_SUBMITTED', evidence=str(receipt_path.relative_to(root)),
            task_id=contract['task_id'], version=contract['version'], protocol_refs=[r['path'] for r in refs])
    except Exception:
        # Preserve the attempt and require user/provider reconciliation on ambiguity.
        if path.is_file():
            state = run_state.read_task(path)
            if (state.get('execution_contract') or {}).get('submission_attempts_used'):
                state['status'] = 'PAUSED_EXCEPTION'
                state['submission_exception'] = 'Submission attempt consumed; reconcile provider task without automatic retry'
                run_state.write_task(path, state)
        raise
    finally:
        lock.unlink()
