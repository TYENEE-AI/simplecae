from pathlib import Path
import json
import copy
import sys
from types import SimpleNamespace
import pytest


@pytest.mark.parametrize('units',['millimeter','inch'])
def test_3mf_refusal_names_real_step_export(tmp_path,units):
    import zipfile
    p=tmp_path/'model.3mf'
    with zipfile.ZipFile(p,'w') as z:z.writestr('3D/3dmodel.model',f'<model unit="{units}"/>')
    from simplecae.geometry import inspect
    from simplecae.mesh_input import load_surface
    for call in (lambda:inspect(p,tmp_path/'out.json'),lambda:load_surface({'path':str(p)})):
        with pytest.raises(ValueError,match='@step.*CADGEN_PY'):call()


@pytest.mark.parametrize('os_name,script',[('Windows','bootstrap.ps1'),('Linux','bootstrap.sh'),('Darwin','platform-installation.md')])
def test_missing_solver_host_guidance(monkeypatch,tmp_path,os_name,script):
    from simplecae import solver
    monkeypatch.setattr(solver.platform,'system',lambda:os_name)
    with pytest.raises(FileNotFoundError,match=script):solver.find_ccx(tmp_path/'absent')


def test_overlapping_ocp_warns_without_import(monkeypatch):
    from simplecae import environment
    monkeypatch.setattr(environment.importlib.metadata,'version',lambda _: '2.2.6.post2')
    assert 'share the OCP namespace' in environment.environment_warnings()[0]
    assert not any(k=='OCP' or k.startswith('OCP.') for k in sys.modules)


def test_native_parameter_provenance(tmp_path):
    from simplecae_scad import _notebook_provenance
    source=tmp_path/'model.py';source.write_text("r = scad.var('r', 3)\n")
    run=SimpleNamespace(config=SimpleNamespace(path=source),dependencies=(),values={'r':4,'unrelated':12})
    value=_notebook_provenance(run,None)
    assert value['parameters']=={'r':4}
    assert value['semantic_family']['source_files_sha256']


def test_native_var_default_preserves_declared_units(tmp_path):
    from simplecae_scad import _notebook_provenance
    source=tmp_path/'model.py';source.write_text("length = scad.var('length', 20, unit='mm')\n")
    Var=type('Var',(),{'__module__':'simplecadapi.parameters','default':20})
    run=SimpleNamespace(config=SimpleNamespace(path=source),dependencies=(),values={'length':Var()})
    assert _notebook_provenance(run,None)['parameters']=={'length':20}


def test_native_parameter_name_need_not_equal_python_binding(tmp_path):
    from simplecae_scad import _notebook_provenance
    source=tmp_path/'model.py';source.write_text("radius_value = scad.var('root_radius', 3)\n")
    run=SimpleNamespace(config=SimpleNamespace(path=source),dependencies=(),values={'radius_value':4})
    assert _notebook_provenance(run,None)['parameters']=={'root_radius':4}


def test_runtime_copy_identity_is_explicit_and_does_not_switch(monkeypatch,tmp_path):
    from simplecae.environment import runtime_copies
    home=tmp_path/'codex';active=tmp_path/'active';other=home/'skills/simplecae'
    for root,text in [(active,'current'),(other,'old')]:
        root.mkdir(parents=True);(root/'SKILL.md').write_text(text)
    monkeypatch.setenv('CODEX_HOME',str(home))
    r=runtime_copies(active,[other,active])
    assert len(r['known_copies'])==2 and r['multiple_copies_detected']
    assert r['active_resource_root']==str(active.resolve())
    assert sum(c['active_resources'] for c in r['known_copies'])==1
    assert len({c['skill_sha256'] for c in r['known_copies']})==2
    with pytest.raises(ValueError,match='SKILL.md'):runtime_copies(active,[tmp_path/'absent'])


def test_semantic_contract_changes_selector_not_parameter_value(tmp_path):
    from simplecae.region_rules import region_contract
    from simplecae.case import sha256
    model=tmp_path/'a.step';model.write_text('source revision')
    manifest=tmp_path/'manifest.json'
    p={'generator':'simplecadapi','generator_version':'2.2.6.post2','definition_id':'rev1','revision':'1',
       'content_hash':sha256(model),'parameters':{'r':3},'source_files_sha256':{'model.py':'a'*64},
       'semantic_family':{'source_files_sha256':{'model.py':'a'*64},'occurrence':None}}
    data={'schema':'simplecae.interface_manifold/2','frame':'part_local','part':{'solid_id':1},'provenance':p,
          'regions':{'load':{'faces':[{'area_mm2':10}],'face_count':1,'surface_types':['Plane'],'native_selector':{'tag':'interface.load'}}}}
    manifest.write_text(json.dumps(data));case={'model':{'path':str(model),'interface_manifest':str(manifest)}}
    before=region_contract(case)
    model.write_text('different geometry');p.update(content_hash=sha256(model),definition_id='rev2',parameters={'r':4})
    data['regions']['load']['faces'][0]['area_mm2']=12;manifest.write_text(json.dumps(data))
    assert before==region_contract(case)
    data['regions']['load']['native_selector']['tag']='interface.changed';manifest.write_text(json.dumps(data))
    assert before!=region_contract(case)


def test_cad_material_label_never_changes_properties(tmp_path):
    from simplecae.cad_metadata import observations
    from simplecae.case import sha256
    model=tmp_path/'a.step';model.write_text('solid')
    manifest=tmp_path/'manifest.json';manifest.write_text(json.dumps({'schema':'simplecae.interface_manifold/2',
        'provenance':{'generator':'scad','generator_version':'2','definition_id':'a','revision':'1','content_hash':sha256(model),
                      'cad_material_label':'6061','cad_density_kg_m3':2700}}))
    case={'model':{'path':str(model),'interface_manifest':str(manifest)},'material':{'density_kg_m3':7800}}
    before=copy.deepcopy(case);result=observations(case)
    assert case==before and result[0]['warnings'] and result[0]['cad_material_label']=='6061'


def test_release_does_not_ship_notebook_cache(tmp_path):
    from simplecae.release import delivery_files
    cache=tmp_path/'examples'/'x'/'__marimo__'/'cache';cache.parent.mkdir(parents=True);cache.write_text('cache')
    assert cache not in delivery_files(tmp_path)
