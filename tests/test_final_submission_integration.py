import copy
import json
import subprocess
from pathlib import Path

import pytest

from production_control import final_submission as fs
from production_control import execution_contract, orchestrator, protocol_fingerprint, protocol_versions, run_state
from production_control.final_packet_qa import review


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')


def packet(project):
    image = project / 'snapshots' / 'reference.png'
    image.parent.mkdir(parents=True, exist_ok=True)
    image.write_bytes(b'offline-reference-fixture')
    nodes = [{'nodeId': n, 'fieldName': k, 'fieldValue': v} for n, k, v in [
        ('25', 'value', 'approved prompt'), ('28', 'value', '8'),
        ('26', 'megapixels', '1.8'), ('26', 'aspect_ratio', '16:9'),
        ('1', 'image', 'uploaded-reference.png'), ('9', 'audio', 'None')]]
    return {'schema': 'rh-final-submission/v1', 'qa_model': fs.QA_MODEL,
            'settings': {'prompt': 'approved prompt', 'duration': 8, 'megapixels': 1.8, 'aspect_ratio': '16:9'},
            'payload': {'workflowId': 'offline-workflow', 'instanceType': 'offline-instance', 'nodeInfoList': nodes},
            'assets': [{'path': str(image), 'sha256': fs.digest_file(image), 'node_id': '1',
                        'uploaded_filename': 'uploaded-reference.png'}], 'disabled_audio_nodes': ['9']}


def approved(project):
    p = packet(project)
    qa = {'overall': 'PASS', 'qa_model': fs.QA_MODEL, 'reviewed_packet_sha256': fs.digest_packet(p),
          'checks': [{'name': 'fixture', 'status': 'PASS'}]}
    invocation = {'requested_model': fs.QA_MODEL, 'status': 'COMPLETED', 'session_id': 'OFFLINE-TEST',
                  'started_at': 'test-start', 'completed_at': 'test-end', 'packet_sha256': fs.digest_packet(p),
                  'report_sha256': fs.digest_packet(qa), 'evidence_type': 'client_execution_record'}
    write(project / 'packet.json', p)
    write(project / 'qa.json', qa)
    write(project / 'invocation.json', invocation)
    return p, qa, invocation


@pytest.mark.parametrize('change', ['prompt', 'duration', 'upload', 'audio', 'workflow', 'image'])
def test_changed_packet_or_snapshot_invalidates_qa(tmp_path, change):
    p, _, _ = approved(tmp_path)
    if change == 'image':
        Path(p['assets'][0]['path']).write_bytes(b'changed-identity')
    elif change == 'workflow':
        p['payload']['workflowId'] = 'new-workflow'
    else:
        positions = {'prompt': 0, 'duration': 1, 'upload': 4, 'audio': 5}
        p['payload']['nodeInfoList'][positions[change]]['fieldValue'] = 'changed'
        write(tmp_path / 'packet.json', p)
    if change == 'workflow':
        write(tmp_path / 'packet.json', p)
    with pytest.raises(ValueError):
        fs.load_approved_packet(tmp_path / 'packet.json', tmp_path / 'qa.json')


def test_real_ai_app_webapp_id_is_valid_without_adding_workflow_id(tmp_path):
    p = packet(tmp_path)
    p['payload']['webappId'] = p['payload'].pop('workflowId')
    before = fs.digest_packet(p)
    assert fs.validate_packet(p) is p
    assert 'workflowId' not in p['payload']
    assert fs.digest_packet(p) == before


def test_asset_snapshot_survives_source_change_and_recovers_exact_bytes(tmp_path):
    original = tmp_path / 'a.png'
    original.write_bytes(b'identity')
    digest = fs.digest_file(original)
    snapshot_dir = tmp_path / 'snapshots'
    assets = [{'path': str(original), 'sha256': digest}]
    frozen = fs.freeze_assets(assets, snapshot_dir, [tmp_path])
    original.write_bytes(b'new identity')
    assert fs.freeze_assets(assets, snapshot_dir, [tmp_path]) == frozen
    snapshot = Path(frozen[0]['path'])
    snapshot.unlink()
    exact = tmp_path / 'b.png'
    exact.write_bytes(b'identity')
    duplicate = tmp_path / 'c.png'
    duplicate.write_bytes(b'identity')
    fs.freeze_assets(assets, snapshot_dir, [tmp_path])
    events = [json.loads(line) for line in (snapshot_dir / 'snapshot_recovery.jsonl').read_text(encoding='utf-8').splitlines()]
    assert events[-1]['source'] == str(exact)
    assert fs.digest_file(snapshot) == digest
    snapshot.write_bytes(b'corrupt')
    with pytest.raises(ValueError, match='SNAPSHOT_CHANGED'):
        fs.freeze_assets(assets, snapshot_dir, [tmp_path])


def test_fixed_qa_dispatch_records_client_session_and_separates_content_fail(tmp_path):
    p, _, _ = approved(tmp_path)
    def runner(command, **kwargs):
        assert command[command.index('--model') + 1] == fs.QA_MODEL
        assert 'Do not invent' in kwargs['input']
        assert "separators=(',', ':'), allow_nan=False).encode('utf-8')" in kwargs['input']
        assert "hashlib.sha256(canonical_bytes).hexdigest()" in kwargs['input']
        assert 'raw file byte hash is NOT' in kwargs['input']
        report = {'overall': 'FAIL', 'qa_model': fs.QA_MODEL, 'reviewed_packet_sha256': fs.digest_packet(p),
                  'checks': [{'name': 'content', 'status': 'FAIL', 'reason': 'offline test'}]}
        write(Path(command[command.index('--output-last-message') + 1]), report)
        return subprocess.CompletedProcess(command, 0, '{"type":"thread.started","thread_id":"MOCK-SESSION"}\n', '')
    result = review(tmp_path / 'packet.json', tmp_path / 'review', executable='offline-codex', runner=runner)
    assert result['status'] == 'COMPLETED'
    assert result['content_verdict'] == 'FAIL'
    assert result['session_id'] == 'MOCK-SESSION'
    def failed(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, '', 'offline failure')
    with pytest.raises(ValueError, match='QA_INVOCATION_EXCEPTION'):
        review(tmp_path / 'packet.json', tmp_path / 'failed', executable='offline-codex', runner=failed)
    assert json.loads((tmp_path / 'failed/qa_invocation.json').read_text(encoding='utf-8'))['status'] == 'EXECUTION_EXCEPTION'


def test_packet_hash_ignores_json_formatting_but_detects_content_changes(tmp_path):
    p, _, _ = approved(tmp_path)
    original = fs.digest_packet(p)
    path = tmp_path / 'packet.json'
    path.write_text(json.dumps(dict(reversed(list(p.items()))), ensure_ascii=False, indent=4) + '\n', encoding='utf-8')
    assert fs.digest_file(path) != original
    fs.load_approved_packet(path, tmp_path / 'qa.json')
    changed = json.loads(path.read_text(encoding='utf-8'))
    changed['payload']['webappId'] = 'changed-provider-binding'
    write(path, changed)
    with pytest.raises(ValueError, match='QA_PACKET_HASH_MISMATCH'):
        fs.load_approved_packet(path, tmp_path / 'qa.json')


def submit_state(project):
    p, _, _ = approved(project)
    console = Path(__file__).resolve().parents[1]
    chain = json.loads((console / 'skills/skill-chain.json').read_text(encoding='utf-8'))
    c = execution_contract.build_contract(chain=chain, project_root=project, run_id='RUN-OFFLINE', task_id='T',
        segment='T', version='v1', execution_model='gpt-6.1-sol', production_level='L1',
        image_assets_required=False, storyboard_required=False, provider='runninghub')
    c['current_step_id'] = 'S09'
    orchestrator.start(project/'unused.json', chain, c['run_id'], c['contract_id'], project_root=project, contract=c)
    fs.bind_packet(project, c['run_id'], 'packet.json')
    path = project/'workflow/runs/RUN-OFFLINE.json'
    state = run_state.read_task(path)
    c = state['execution_contract']
    c.update(current_step_id='S11', current_owner='executor', provider_authorized=True)
    c['final_submission'].update(qa_path='qa.json', invocation_path='invocation.json')
    (project/'authorization.md').write_text('OFFLINE TEST ONLY', encoding='utf-8')
    auth = {'run_id': c['run_id'], 'contract_id': c['contract_id'], 'provider': 'runninghub',
            'scope': 'single_video_submission', 'max_submissions': 1, 'evidence': 'authorization.md',
            'evidence_sha256': fs.digest_file(project/'authorization.md')}
    c['submission_authorization'] = auth
    state['submission_authorizations'] = [auth]
    state['protocol_attestation'] = {'status':'PASS', 'contract_id':c['contract_id'],
        'manifest_fingerprint':c['protocol_manifest_fingerprint'], 'scope_gate':'G6',
        'protocol_paths':sorted(protocol_versions.scoped_paths(c))}
    state['current_step'] = next(s['skill'] for s in c['steps'] if s['id'] == 'S11')
    run_state.write_task(path, state)
    return p, path


def test_submit_uses_identical_payload_once_and_retains_task(tmp_path):
    p, path = submit_state(tmp_path)
    calls = []
    def send(payload):
        calls.append(copy.deepcopy(payload))
        return {'task_id': 'OFFLINE-TASK', 'status': 'QUEUED'}
    state = fs.submit_bound_packet(tmp_path, 'RUN-OFFLINE', send)
    assert calls == [p['payload']]
    assert state['execution_contract']['provider_task_id'] == 'OFFLINE-TASK'
    assert state['execution_contract']['submission_attempts_used'] == 1
    with pytest.raises(ValueError):
        fs.submit_bound_packet(tmp_path, 'RUN-OFFLINE', send)
    assert len(calls) == 1


def test_submit_timeout_consumes_attempt_and_never_retries(tmp_path):
    _, path = submit_state(tmp_path)
    def send(payload):
        raise TimeoutError('offline ambiguous request')
    with pytest.raises(TimeoutError):
        fs.submit_bound_packet(tmp_path, 'RUN-OFFLINE', send)
    state = run_state.read_task(path)
    assert state['execution_contract']['submission_attempts_used'] == 1
    assert state['status'] == 'PAUSED_EXCEPTION'
    with pytest.raises(ValueError, match='SUBMISSION_ALREADY_CONSUMED'):
        fs.submit_bound_packet(tmp_path, 'RUN-OFFLINE', send)


def test_protocol_snapshots_diff_and_unrelated_drift(tmp_path, monkeypatch):
    monkeypatch.setattr(protocol_fingerprint, 'REQUIRED_CORE_FILES', ['identity.md'])
    monkeypatch.setattr(protocol_fingerprint, 'RUNTIME_CONTROL_FILES', [])
    for name in ['identity.md','current.md','other.md']:
        (tmp_path/name).write_text(name+' v1\n', encoding='utf-8')
    monkeypatch.setattr(protocol_fingerprint, 'registered_protocol_files', lambda root=None: ['identity.md','current.md','other.md'])
    old = protocol_fingerprint.generate(tmp_path)
    c = {'protocol_root':str(tmp_path), 'protocol_manifest_fingerprint':old['fingerprint'], 'current_step_id':'S09',
         'protocol_snapshot_hashes':{e['path']:e['sha256'] for e in old['files']},
         'steps':[{'id':'S09','gate':['G5'],'applicable':True,'protocol_refs':[{'path':'current.md','sha256':fs.digest_file(tmp_path/'current.md')}]}]}
    (tmp_path/'other.md').write_text('unrelated change\n', encoding='utf-8')
    assert protocol_versions.check_current(c) == []
    new = protocol_fingerprint.generate(tmp_path)
    impact = protocol_versions.impact_report(c,tmp_path,new)
    assert impact['confirmation_required_paths'] == []
    assert '-other.md v1' in impact['changes'][0]['diff']
    (tmp_path/'identity.md').write_text('changed authorization/identity\n', encoding='utf-8')
    assert protocol_versions.check_current(c)
    new = protocol_fingerprint.generate(tmp_path)
    assert 'identity.md' in protocol_versions.impact_report(c,tmp_path,new)['confirmation_required_paths']


def test_generic_s09_records_the_reviewed_packet_not_template(tmp_path):
    from production_control.progress import append_event
    _, path = submit_state(tmp_path)
    state = run_state.read_task(path)
    c = state['execution_contract']
    c['current_step_id'] = 'S09'
    c['current_owner'] = 'producer'
    step = next(s for s in c['steps'] if s['id'] == 'S09')
    state['current_step'] = step['skill']
    state['protocol_attestation']['scope_gate'] = 'G5'
    state['protocol_attestation']['protocol_paths'] = sorted(protocol_versions.scoped_paths(c))
    run_state.write_task(path, state)
    refs = [r['path'] for r in step['protocol_refs']]
    common = dict(step='S09', gate='G5', task_id=c['task_id'], version=c['version'],
                  qa_level='C', affected_files=['packet.json'], protocol_refs=refs, writer_model=fs.QA_MODEL)
    write(tmp_path/'template.json', {'duration': 5, 'audio': 'example'})
    with pytest.raises(ValueError, match='FINAL_PACKET_QA_SOURCE_MISMATCH'):
        append_event(tmp_path,c['run_id'],evidence='template.json',outcome='SUBMITTED_FOR_QA',
                     actor=c['execution_model'],role='producer',**common)
    append_event(tmp_path,c['run_id'],evidence='packet.json',outcome='SUBMITTED_FOR_QA',
                 actor=c['execution_model'],role='producer',**common)
    result = append_event(tmp_path,c['run_id'],evidence='qa.json',outcome='COMPLETED',role='qa',
                          actor=fs.QA_MODEL,execution_model=c['execution_model'],qa_conclusion='PASS',
                          qa_invocation_evidence='invocation.json',elapsed_seconds=1,next_step='G6 adaptation',**common)
    assert result['events'][-1]['reviewed_packet_sha256'] == c['final_submission']['packet_sha256']
    assert result['execution_contract']['final_submission']['qa_path'] == 'qa.json'


def test_migration_requires_confirmation_and_preserves_consumed_history(tmp_path, monkeypatch):
    from tools.migrate_run_protocol import migrate
    authority = tmp_path/'authority'
    authority.mkdir()
    monkeypatch.setattr(protocol_fingerprint,'REQUIRED_CORE_FILES',['identity.md'])
    monkeypatch.setattr(protocol_fingerprint,'RUNTIME_CONTROL_FILES',[])
    monkeypatch.setattr(protocol_fingerprint,'registered_protocol_files',lambda root=None:['identity.md','other.md'])
    (authority/'identity.md').write_text('identity v1\n',encoding='utf-8')
    (authority/'other.md').write_text('other v1\n',encoding='utf-8')
    old = protocol_fingerprint.generate(authority)
    project=tmp_path/'project'
    path=project/'workflow/runs/RUN-M.json'
    state={'run_id':'RUN-M','status':'RUNNING','events':[{'outcome':'TASK_SUBMITTED','task_id':'old'}],
           'protocol_attestation':{'status':'PASS','protocol_paths':['identity.md']},
           'execution_contract':{'protocol_root':str(authority),'protocol_manifest_fingerprint':old['fingerprint'],
               'protocol_snapshot_hashes':{e['path']:e['sha256'] for e in old['files']},'current_step_id':'S12',
               'provider_task_id':'KEEP-TASK','submission_count':1,'submission_attempts_used':1,'budget_cny':18,
               'steps':[{'id':'S12','applicable':True,'gate':['G6'],'protocol_refs':[]}]}}
    write(path,state)
    (authority/'identity.md').write_text('identity v2\n',encoding='utf-8')
    protocol_fingerprint.generate(authority)
    before=path.read_bytes()
    impact=migrate(project,'RUN-M',inspect_only=True)
    assert '-identity v1' in impact['changes'][0]['diff']
    assert path.read_bytes()==before
    with pytest.raises(ValueError,match='PROTOCOL_CHANGE_CONFIRMATION_REQUIRED'):
        migrate(project,'RUN-M')
    assert path.read_bytes()==before
    (project/'confirmed.md').write_text('OFFLINE TEST confirmation',encoding='utf-8')
    migrate(project,'RUN-M',confirmed_paths=['identity.md'],confirmation_evidence='confirmed.md')
    result=json.loads(path.read_text(encoding='utf-8'))
    assert result['events']==state['events']
    for key in ['submission_count','submission_attempts_used','budget_cny','provider_task_id']:
        assert result['execution_contract'][key]==state['execution_contract'][key]
    assert result['protocol_attestation']['status']=='STALE'
