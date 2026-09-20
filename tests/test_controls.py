import json
from pathlib import Path
from production_control.asset_decider import decide
from production_control.payload_compiler import compile_payload
from production_control.qa_report import validate_report
from production_control.capabilities import get_capability
from production_control.skill_chain_validator import validate_chain as validate_skill_chain
from production_control.image_channel import choose_image_channel, validate_image_record
from production_control.capabilities import get_image_capability, IMAGE_MODEL

ROOT=Path(__file__).parents[1]
def load(n): return json.loads((ROOT/'examples'/n).read_text(encoding='utf-8'))

def test_asset_decision_routes_complex_to_storyboard_when_authorized():
    d=decide({'production_unit_id':'U1','risk_flags':['physical_contact']},{'character_master','scene_master'},{'allow_storyboard_generation':True})
    assert d['recommended_route']=='STORYBOARD_REQUIRED'
    assert d['degraded'] is False

def test_asset_decision_degrades_without_storyboard_authorization():
    d=decide({'production_unit_id':'U1','risk_flags':['physical_contact']},{'character_master','scene_master'})
    assert d['recommended_route']=='DEGRADED_DIRECT'
    assert d['degraded'] is True
    assert d['prompt_only']=='PASS'
    assert d['fallback_notes']

def test_missing_tail_frame_does_not_block():
    d=decide({'production_unit_id':'U1','risk_flags':['real_tail_frame_required']},{'character_master','scene_master'})
    assert d['recommended_route']=='PROMPT_ONLY_READY'
    assert any('degrade' in note for note in d['fallback_notes'])

def test_reason_matches_missing_assets():
    d=decide({'production_unit_id':'U1','risk_flags':['none']},set())
    assert d['recommended_route']=='ASSET_PLAN_REQUIRED'
    assert '身份权威缺失' in d['reason']

def test_capabilities_cover_three_providers():
    assert {get_capability(x)['provider'] for x in ('runninghub','xiaoyunque','libtv')}=={'runninghub','xiaoyunque','libtv'}

def test_pre_qa_requires_all_checks():
    assert validate_report({'status':'PASS','checks':{'script':'PASS'}},'pre_generation')

def test_qa_pass_with_failed_check_is_rejected():
    report={'status':'PASS','checks':{'script':'FAIL','assets':'PASS','prompt':'PASS','skill':'PASS'}}
    assert any('requires every check to be PASS' in e for e in validate_report(report,'pre_generation'))

def test_valid_qa_report_passes():
    checks={x:'PASS' for x in ('script','assets','prompt','skill')}
    assert validate_report({'status':'PASS','checks':checks},'pre_generation')==[]

def test_payload_requires_authorization():
    c=load('production_contract.valid.json'); p=load('prompt_unit.direct.json')
    d=decide({'production_unit_id':'EP01-U01','risk_flags':['none']},{'character_master','scene_master'})
    try: compile_payload(c,p,d)
    except ValueError as e: assert 'not authorized' in str(e)
    else: assert False

def test_payload_blocks_route_mode_mismatch():
    c=load('production_contract.valid.json'); p=load('prompt_unit.direct.json')
    c['authorization']['video_submission_authorized']=True
    c['authorization']['max_submissions']=1
    d={'production_unit_id':'EP01-U01','recommended_route':'STORYBOARD_REQUIRED','degraded':False,'fallback_notes':[]}
    try: compile_payload(c,p,d)
    except ValueError as e: assert 'does not match route' in str(e)
    else: assert False

def test_payload_allows_degraded_direct_route():
    c=load('production_contract.valid.json'); p=load('prompt_unit.direct.json')
    c['authorization']['video_submission_authorized']=True
    c['authorization']['max_submissions']=1
    c['storyboard_mode']='degraded_direct'
    d=decide({'production_unit_id':'EP01-U01','risk_flags':['physical_contact']},{'character_master','scene_master'})
    payload=compile_payload(c,p,d)
    assert payload['degraded'] is True
    assert payload['submission_authorized'] is True

def test_skill_chain_is_complete_and_ordered():
    assert validate_skill_chain() == []

def test_images_default_to_local_subscription_channel():
    d=choose_image_channel(quota_available=True)
    assert d['image_channel']=='gpt_image2_local_subscription'
    assert d['model']==IMAGE_MODEL
    assert d['cash_cost_cny']==0

def test_exhausted_quota_falls_back_to_runninghub_when_authorized():
    d=choose_image_channel(False, fallback_reason='subscription_quota_exhausted', runninghub_authorized=True)
    assert d['image_channel']=='gpt_image2_runninghub_workflow'
    assert d['authorized'] is True
    assert not d.get('blocked')

def test_exhausted_quota_without_authorization_is_blocked():
    d=choose_image_channel(False, fallback_reason='subscription_quota_exhausted')
    assert d['blocked'] is True

def test_fallback_requires_a_recorded_reason():
    try: choose_image_channel(False, runninghub_authorized=True)
    except ValueError as e: assert 'recorded reason' in str(e)
    else: assert False

def test_image_record_must_be_gpt_image_2():
    record={'asset_role':'character_master','image_channel':'gpt_image2_local_subscription','model':'sd-xl','evidence':'qa/img.json'}
    assert any('gpt-image-2' in e for e in validate_image_record(record))

def test_valid_local_image_record_passes():
    record={'asset_role':'character_master','image_channel':'gpt_image2_local_subscription','model':IMAGE_MODEL,'conversation_url':'https://chatgpt.com/c/1','evidence':'qa/img.json'}
    assert validate_image_record(record)==[]

def test_runninghub_image_record_requires_task_id_and_authorization():
    record={'asset_role':'keyframe','image_channel':'gpt_image2_runninghub_workflow','model':IMAGE_MODEL,'evidence':'qa/img.json'}
    errors=validate_image_record(record)
    assert any('fallback_reason' in e for e in errors)
    assert any('authorization' in e for e in errors)
    assert any('task_id' in e for e in errors)

def test_reference_count_respects_channel_limit():
    assert get_image_capability('gpt_image2_runninghub_workflow')['max_references']==3
    record={'asset_role':'keyframe','image_channel':'gpt_image2_runninghub_workflow','model':IMAGE_MODEL,'fallback_reason':'subscription_quota_exhausted','authorized':True,'task_id':'RH-1','evidence':'qa/img.json','reference_count':5}
    assert any('at most 3' in e for e in validate_image_record(record))
