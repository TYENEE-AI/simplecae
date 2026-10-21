"""Generic fixes reproduced by multi-persona CAD/CAE use, not product rules."""
import copy
import json
from pathlib import Path
import subprocess
import sys

import pytest
from simplecae.case import write_json
from simplecae.task import start_task,task_status,record_task_check,brief_task_status,_analysis_note,_case_paths
from test_task import request,evidence,ROOT


def test_bad_force_units_are_rejected_before_workspace_or_worker(tmp_path,monkeypatch):
    p=request(tmp_path,fem=True);m=json.loads(p.read_text(encoding='utf8'))
    m['cases']['task-deflection']['loads'][0]['total_force_n']=['5kg',0,-1]
    write_json(p,m)
    monkeypatch.setattr(subprocess,'Popen',lambda *a,**k:pytest.fail('Input validation must not start a worker'))
    with pytest.raises(ValueError,match='Check task-deflection: invalid numerical input'):
        start_task(p,tmp_path/'task')
    assert not (tmp_path/'task').exists()


def test_direct_record_keeps_explicit_revision_and_artifact_hash_guards(tmp_path):
    s=start_task(request(tmp_path),tmp_path/'task');cid=s['checks'][0]['id']
    artifact=tmp_path/'measurement.json';write_json(artifact,{'gap_mm':.4})
    for rev in (None,'old-revision'):
        with pytest.raises(ValueError,match='revision_sha256'):
            record_task_check(tmp_path/'task',cid,artifacts=[artifact],outcome='pass',observations=['Gap .4mm meets .3mm limit'],revision_sha256=rev)
    s=record_task_check(tmp_path/'task',cid,artifacts=[artifact],outcome='pass',
        observations=['Gap .4mm meets .3mm limit'],limitations=['Nominal CAD only'],revision_sha256=s['revision_sha256'])
    assert s['checks'][0]['outcome']=='pass' and s['checks'][0]['latest']['kind']=='externally_recorded'
    assert not s['whole_product_pass_available']
    write_json(artifact,{'gap_mm':.1})
    assert task_status(tmp_path/'task')['checks'][0]['outcome']=='insufficient_evidence'


@pytest.mark.parametrize('missing',['outcome','observations','artifacts'])
def test_direct_record_cannot_invent_a_pass_from_an_artifact(tmp_path,missing):
    s=start_task(request(tmp_path),tmp_path/'task');artifact=tmp_path/'actual.json';write_json(artifact,{'observed':True})
    fields={'artifacts':[artifact],'outcome':'pass','observations':['Actual declared measurement'], 'revision_sha256':s['revision_sha256']}
    fields.pop(missing)
    with pytest.raises(ValueError):record_task_check(tmp_path/'task',s['checks'][0]['id'],**fields)
    assert all(c['outcome']=='pending' for c in task_status(tmp_path/'task')['checks'])


def test_direct_evidence_cannot_override_fem_or_mix_with_file_contract(tmp_path):
    s=start_task(request(tmp_path,fem=True),tmp_path/'task');artifact=tmp_path/'actual.json';write_json(artifact,{'value':1})
    with pytest.raises(ValueError,match='FEM needs computed'):
        record_task_check(tmp_path/'task','task-deflection',artifacts=[artifact],outcome='pass',observations=['actual'],revision_sha256=s['revision_sha256'])
    ep=evidence(tmp_path,s,'real-mount')
    with pytest.raises(ValueError,match='not both'):
        record_task_check(tmp_path/'task','real-mount',ep,artifacts=[artifact])


def test_brief_omits_history_but_keeps_pending_unknowns_and_provenance(tmp_path):
    s=start_task(request(tmp_path),tmp_path/'task')
    s=record_task_check(tmp_path/'task',s['checks'][0]['id'],evidence(tmp_path,s))
    small=brief_task_status(s)
    assert small['status']==s['status'] and small['unknowns']==s['unknowns']
    assert small['remaining_required_checks']==s['remaining_required_checks']
    assert small['completion_counts']['pass']==1
    assert small['checks'][0]['evidence_kind']=='externally_recorded'
    assert all('history' not in c for c in small['checks'])
    assert json.loads(Path(small['full_report']).read_text(encoding='utf8'))['checks'][0]['history']


def test_explicit_depth_gate_has_a_command_but_never_changes_the_physics(tmp_path):
    s=start_task(request(tmp_path),tmp_path/'task')
    row=s['checks'][0];row.update(outcome='insufficient_evidence',next_action='choose_analysis_depth')
    row['latest']={'analysis':{'focus':'analysis_depth','worker_started':False}}
    small=brief_task_status(s)
    assert small['checks'][0]['suggested_command_args']==['task','run',s['session'],'--check',row['id'],'--depth','detailed']
    assert not small['checks'][0]['analysis']['worker_started']


@pytest.mark.parametrize('direction,joint,total,expected',[
    ([0,0,1],[0,0,.3],[0,0,.35],True),
    ([0,0,1],[1,0,0],[0,0,.35],False),
    ([0,0,2],[0,0,.3],[0,0,.35],True),
    (None,[.2,.2,0],[.25,.25,0],True)])
def test_joint_guidance_uses_the_actual_task_projection_not_sum_of_magnitudes(tmp_path,direction,joint,total,expected):
    spec={'name':'tip','max_displacement_mm':.15}
    if direction is not None:spec['direction']=direction
    p=tmp_path/'raw.json'
    write_json(p,{'case':{'probes':[spec]},'poses':[{'name':'pose','task_probe_assessment':{
        'displacement_contributions':{'full':{'tip':{'joint_vector_mm':joint,
          'link_vector_mm':[a-b for a,b in zip(total,joint)],'total_vector_mm':total}}}}}]})
    usage={'status':'fail_under_stated_model','governing':{'name':'pose/probe:tip'},
        'confirmed_failed_criteria':{'pose/probe:tip':{}},'cad_iteration':{'reanalysis_trigger':'after_design_change'}}
    review={'execution':{'state':'completed','worker_started':True},'result':{'path':str(p)}}
    n=_analysis_note(review,usage)
    assert (n.get('focus')=='joint_compliance') is expected
    if expected:
        assert n['joint_contribution_mm']>.15
    usage['status']='insufficient_evidence'
    assert _analysis_note(review,usage).get('focus') is None


def test_cli_direct_record_and_brief_use_real_files(tmp_path):
    s=start_task(request(tmp_path),tmp_path/'task');artifact=tmp_path/'actual.json';write_json(artifact,{'gap_mm':.4})
    cmd=[sys.executable,str(ROOT/'scripts/simplecae_cli.py'),'task','record',str(tmp_path/'task'),
         '--check',s['checks'][0]['id'],'--artifact',str(artifact),'--revision',s['revision_sha256'],
         '--outcome','pass','--observation','Measured .4mm gap >= .3mm','--limitation','Nominal CAD only','--brief']
    p=subprocess.run(cmd,capture_output=True,encoding='utf8')
    assert p.returncode==0,p.stdout+p.stderr
    result=json.loads(p.stdout)
    assert result['checks'][0]['outcome']=='pass' and result['checks'][0]['evidence_kind']=='externally_recorded'
    assert result['remaining_required_checks'] and not result['whole_product_pass_available']


def test_joint_and_link_cancellation_is_retained_as_vectors(tmp_path):
    p=tmp_path/'raw.json'
    write_json(p,{'case':{'probes':[{'name':'tip','max_displacement_mm':.15,'direction':[0,0,1]}]},
        'poses':[{'name':'pose','task_probe_assessment':{'displacement_contributions':{
        'full':{'tip':{'joint_vector_mm':[0,0,.3],'link_vector_mm':[0,0,-.1],'total_vector_mm':[0,0,.2]}}}}}]})
    usage={'status':'fail_under_stated_model','governing':{'name':'pose/probe:tip'},
        'confirmed_failed_criteria':{'pose/probe:tip':{}},'cad_iteration':{'reanalysis_trigger':'after_design_change'}}
    note=_analysis_note({'execution':{'state':'completed'},'result':{'path':str(p)}},usage)
    assert note['joint_contribution_mm']==pytest.approx(.3)
    assert note['link_contribution_mm']==pytest.approx(.1)
    assert note['total_mm']==pytest.approx(.2)


def test_referenced_interface_and_package_roots_keep_the_original_base(tmp_path):
    sidecar=tmp_path/'ports.json';write_json(sidecar,{'source':'explicit test metadata'})
    package=tmp_path/'robot-assets';package.mkdir()
    value={'model':{'path':str(ROOT/'examples/preview/beam.step'),
        'interface_manifest':'ports.json','package_roots':{'robot':'robot-assets'}}}
    tracked=set();_case_paths(value,tmp_path,tracked)
    assert value['model']['interface_manifest']==str(sidecar.resolve())
    assert value['model']['package_roots']['robot']==str(package.resolve())
    assert sidecar in tracked
