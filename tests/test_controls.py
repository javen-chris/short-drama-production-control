import json
from pathlib import Path
from production_control.asset_decider import decide
from production_control.payload_compiler import compile_payload
from production_control.qa_report import validate_report
from production_control.capabilities import get_capability

ROOT=Path(__file__).parents[1]
def load(n): return json.loads((ROOT/'examples'/n).read_text(encoding='utf-8'))
def test_asset_decision_routes_complex_to_storyboard():
    d=decide({'production_unit_id':'U1','risk_flags':['physical_contact']},{'character_master','scene_master'})
    assert d['recommended_route']=='STORYBOARD_REQUIRED'
def test_capabilities_cover_three_providers():
    assert {get_capability(x)['provider'] for x in ('runninghub','xiaoyunque','libtv')}=={'runninghub','xiaoyunque','libtv'}
def test_pre_qa_requires_all_checks():
    assert validate_report({'status':'PASS','checks':{'script':'PASS'}},'pre_generation')
def test_payload_requires_authorization():
    c=load('production_contract.valid.json'); p=load('prompt_unit.direct.json'); d=decide({'production_unit_id':'U1','risk_flags':['none']},{'character_master','scene_master'}); 
    try: compile_payload(c,p,d)
    except ValueError as e: assert 'not authorized' in str(e)
    else: assert False

