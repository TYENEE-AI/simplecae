"""Cross-revision binding, bounded display degradation and actionable advice."""
from pathlib import Path
import copy,json
import pytest
from simplecae.case import write_json,load_case,sha256
from simplecae.region_rules import bind_regions,select_region,region_contract
from simplecae.bridge import resolve_interfaces

ROOT=Path(__file__).resolve().parents[1]
BEAM=ROOT/'examples/integration/simplecad-beam.step'


def rules():
    return {'schema_version':'simplecae-region-rules-1.0','model_id':'beam',
        'regions':{'mount':{'plane':{'axis':'x','position_mm':0},'face_count':[1,1]},
                   'tip':{'plane':{'axis':'x','position_mm':100},'face_count':[1,1]}}}


def test_rules_rebind_changed_geometry_and_reject_ambiguity(tmp_path):
    import gmsh
    from simplecae.geometry import session,inventory
    spec=tmp_path/'rules.json';write_json(spec,rules());contracts=[]
    for i,width in enumerate((10.,12.)):
        model=tmp_path/f'beam{i}.step'
        with session() as g:
            g.model.occ.addBox(0,0,0,100,width,10);g.model.occ.synchronize();g.write(str(model))
        out=tmp_path/f'binding{i}.json';binding=bind_regions(model,spec,out)
        with session(model,{'path':str(model)}) as g:info=inventory(g,model)
        assert resolve_interfaces(out,info)['regions']==binding['regions']
        contracts.append(region_contract({'model':{'path':str(model),'interface_manifest':str(out)}}))
    assert contracts[0]==contracts[1]
    manifest=json.loads(out.read_text());manifest['regions']['mount']['faces']=manifest['regions']['tip']['faces']
    write_json(out,manifest)
    with pytest.raises(ValueError,match='contradict'):resolve_interfaces(out,info)
    with pytest.raises(ValueError,match='fresh'):bind_regions(model,spec,out)
    too_many={'surface_types':['Plane'],'face_count':[1,1]}
    with pytest.raises(ValueError,match='matched 6'):select_region(info,too_many)
    missing={'plane':{'axis':'x','position_mm':99},'face_count':[1,1]}
    with pytest.raises(ValueError,match='no full CAD face'):select_region(info,missing)


def test_same_names_do_not_hide_changed_rule_or_frame(tmp_path):
    p=tmp_path/'rules.json';write_json(p,rules());out=tmp_path/'bind.json';bind_regions(BEAM,p,out)
    c={'bodies':[{'name':'beam','model':{'path':str(BEAM),'interface_manifest':str(out)}}]}
    original=region_contract(c)
    c['bodies'][0]['placement']={'translation_mm':[10,0,0]}
    assert original!=region_contract(c)
    c['bodies'][0].pop('placement')
    m=json.loads(out.read_text());m['regions']['mount']['rule']['plane']['position_mm']=100;write_json(out,m)
    assert original!=region_contract(c)
    m['model_sha256']='f'*64;write_json(out,m)
    with pytest.raises(ValueError,match='different model'):region_contract(c)


@pytest.mark.parametrize('bad',[{}, {'centroid_bounds_mm':{'x':[None,None]},'face_count':[1,1]},
    {'surface_types':['Plane'],'face_count':[True,2]}, {'surface_types':[],'face_count':[1,1]},
    {'centroid_bounds_mm':{'z':[2,1]},'face_count':[1,1]}])
def test_region_rules_reject_underdefined_or_invalid_selection(bad):
    with pytest.raises((ValueError,TypeError)):select_region({'faces':[]},bad)


def test_preview_fallback_preserves_all_cad_regions_and_disables_fake_picking(tmp_path):
    from simplecae.preflight import surface_data,preview_case
    c=load_case(ROOT/'examples/integration/simplecad-beam-step.case.json')
    full=surface_data(c['model']);small=surface_data(c['model'],12)
    assert full['geometry']==small['geometry']
    assert len(small['triangles'])<=12
    assert small['tessellation']['mode'] in ('coarsened','bounds_only')
    if small['tessellation']['mode']=='bounds_only':
        assert not small['picking_enabled'] and all(x is None for x in small['triangle_faces'])
    p=tmp_path/'case.json';write_json(p,c);preview_case(p,tmp_path/'preview',max_triangles=12)
    report=json.loads((tmp_path/'preview/preview.json').read_text())
    assert report['regions'] and all(r['faces'] for r in report['regions'])
    if not report['display']['picking_enabled']:assert report['support_diagnostics']['rank'] is None
    assert '求解' in (tmp_path/'preview/preview.html').read_text(encoding='utf-8')


def test_mesh_advice_is_source_bound_valid_and_never_changes_input(tmp_path):
    from simplecae.advice import advise
    from simplecae.local_mesh import validate_refinements
    c=load_case(ROOT/'examples/integration/simplecad-beam-step.case.json');c['mesh']['max_elements']=10000
    p=tmp_path/'case.json';write_json(p,c);original=p.read_bytes()
    evidence=tmp_path/'evidence';evidence.mkdir()
    d={'stage':'high_order_optimize','status':'rejected','geometry_sha256':sha256(BEAM),'mesh_size_mm':4.,
        'element_count':100,'adjacent_cad_faces':[{'id':2,'type':'Cylinder','bbox_mm':[0,0,0,2,2,10]}]}
    write_json(evidence/'mesh-diagnostic.json',d)
    a=advise(p,evidence,tmp_path/'advice.json')
    assert not a['automatic_retry'] and p.read_bytes()==original
    entry=next(x['proposed_entry'] for x in a['actions'] if x['kind']=='local_refinement')
    validate_refinements({'local_refinements':[entry]})
    assert entry['selector']['geometry_sha256']==sha256(BEAM)
    c['mesh']['max_elements']=20;write_json(p,c)
    tight=advise(p,evidence,tmp_path/'tight-advice.json')
    assert any(x['kind']=='element_budget' for x in tight['actions'])
    assert any(x['kind']=='mesh_budget_conflict' for x in tight['actions'])
    assert not any(x['kind']=='local_refinement' for x in tight['actions'])
    d['geometry_sha256']='f'*64;write_json(evidence/'mesh-diagnostic.json',d)
    with pytest.raises(ValueError,match='different CAD'):advise(p,evidence,tmp_path/'bad.json')


def test_field_budget_diagnostic_proposal_uses_actual_count(tmp_path):
    from simplecae.advice import advise
    c=load_case(ROOT/'examples/integration/simplecad-beam-step.case.json')
    p=tmp_path/'case.json';write_json(p,c)
    write_json(tmp_path/'resource-diagnostic.json',{'geometry_sha256':sha256(BEAM),'field_value_count':8100000})
    a=advise(p,tmp_path,tmp_path/'advice.json')
    assert next(x for x in a['actions'] if x['kind']=='field_budget')['proposed_max_field_values']>=8100000


def test_old_pass_for_different_load_does_not_stop_current_task(tmp_path,monkeypatch):
    from simplecae.advice import advise
    from simplecae.signals import structural_contract
    import simplecae.signals as signals
    c=load_case(ROOT/'examples/integration/simplecad-beam-step.case.json')
    old=copy.deepcopy(c);old['loads'][0]['total_force_n']=[0,0,-999]
    result={'case':old,'status':'pass_under_stated_model','task_contract':structural_contract(old),
            'source_files_sha256':{str(Path(old['model']['path']).resolve()):sha256(BEAM)}}
    write_json(tmp_path/'result.json',result);write_json(tmp_path/'case.json',c)
    monkeypatch.setattr(signals,'design_signal',lambda _: {'valid_for_comparison':True})
    a=advise(tmp_path/'case.json',tmp_path/'result.json',tmp_path/'advice.json')
    assert not a['same_physics_contract']
    assert a['next_action']=='inspect_unresolved_evidence_no_automatic_retry'


def test_region_manifest_change_invalidates_structural_signal(tmp_path):
    from simplecae.signals import structural_contract,design_signal
    p=tmp_path/'rules.json';write_json(p,rules());manifest=tmp_path/'bindings.json';bind_regions(BEAM,p,manifest)
    c=load_case(ROOT/'examples/integration/simplecad-beam-step.case.json');c['model']['interface_manifest']=str(manifest)
    result={'case':c,'status':'invalid','task_contract':structural_contract(c),
            'source_files_sha256':{str(manifest):sha256(manifest),str(BEAM):sha256(BEAM)}}
    manifest.write_text('{}')
    signal=design_signal(result)
    assert not signal['valid_for_comparison']
    assert any(f['scope']=='region_binding' for f in signal['feedback'] if 'scope' in f)
