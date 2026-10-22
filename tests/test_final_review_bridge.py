import copy
import json
from pathlib import Path
import numpy as np
import pytest
from simplecae.bridge import resolve_interfaces
from simplecae.diagnostics import WorkflowError
from simplecae.case import selector,SELECTOR_TYPES,sha256
from simplecae.geometry import session,inventory


def fixture():
    transform=[[0,-1,0,40],[1,0,0,20],[0,0,1,0],[0,0,0,1]]
    centers=[[1,0,0],[2,0,0],[3,0,0],[4,0,0]]
    info={'geometry_sha256':'a'*64,'solid_count':1,'source_solid_count':2,'source_solid_id':2,
          'faces':[{'id':i+10,'centroid_mm':[40,20+c[0],0],'area_mm2':10,'type':'Plane'} for i,c in enumerate(centers)]}
    manifest={'schema':'simplecae.interface_manifold/2','frame':'part_local','part':{'solid_id':2},
              'placement':{'matrix_4x4':transform},
              'regions':{'mount':{'face_count':4,'surface_types':['Plane'],
                                  'faces':[{'centroid_mm':c,'area_mm2':10} for c in centers]}},
              'provenance':{'generator':'custom','generator_version':'1','definition_id':'mount','revision':'r1','content_hash':'a'*64}}
    return info,manifest


def bind(tmp_path,manifest,info):
    p=tmp_path/'manifest.json';p.write_text(json.dumps(manifest),encoding='utf-8')
    return resolve_interfaces(p,info)


def test_rotated_local_binding(tmp_path):
    info,m=fixture();result=bind(tmp_path,m,info)
    assert result['regions']['mount']==[10,11,12,13]
    assert result['placement_source']=='explicit'


def test_missing_frame_or_placement_never_falls_back(tmp_path):
    info,m=fixture();del m['placement']
    # A tempting wrong face at the untransformed local coordinate must not bind.
    info['faces'][0]['centroid_mm']=[1,0,0]
    with pytest.raises(WorkflowError,match='placement'):bind(tmp_path,m,info)
    m['frame']='world';del m['frame']
    with pytest.raises(ValueError,match='frame'):bind(tmp_path,m,info)


def test_coincident_and_close_signature_ambiguity(tmp_path):
    info,m=fixture();info['faces'].append(dict(info['faces'][0],id=44))
    with pytest.raises(WorkflowError,match='ambiguous_signature'):bind(tmp_path,m,info)
    # Second candidate outside the absolute matching window, but not 10x farther.
    info['faces'][0]['centroid_mm']=[40,21.0005,0]
    info['faces'][-1]['centroid_mm']=[40,21.002,0]
    with pytest.raises(WorkflowError,match='ambiguous_signature'):bind(tmp_path,m,info)


def test_count_type_and_selected_solid_guards(tmp_path):
    info,m=fixture();m['regions']['mount']['face_count']=2
    with pytest.raises(WorkflowError) as error:bind(tmp_path,m,info)
    assert len(error.value.diagnostic['details']['candidate_faces'])==4
    info,m=fixture();info['faces'][0]['type']='Cylinder'
    with pytest.raises(WorkflowError,match='ambiguous_signature'):bind(tmp_path,m,info)
    info,m=fixture();info['source_solid_id']=3
    with pytest.raises(ValueError,match='solid_id'):bind(tmp_path,m,info)


@pytest.mark.parametrize('matrix', [[[1,0],[0,1]], [[2,0,0,0],[0,2,0,0],[0,0,2,0],[0,0,0,1]],
                                  [[1,0,0,0],[0,-1,0,0],[0,0,1,0],[0,0,0,1]]])
def test_non_rigid_placement_refused(tmp_path,matrix):
    info,m=fixture();m['placement']['matrix_4x4']=matrix
    with pytest.raises(ValueError,match='rigid'):bind(tmp_path,m,info)


def test_legacy_assembly_refused(tmp_path):
    info,_=fixture()
    m={'schema_version':'1.0','generator':'custom','model_id':'x','revision':'r','model_sha256':'a'*64,'regions':{'x':{'faces':[{'area_mm2':10,'centroid_mm':[40,21,0]}]}}}
    with pytest.raises(ValueError,match='v1.*assembly'):bind(tmp_path,m,info)
    info['source_solid_count']=1
    assert bind(tmp_path,m,info)['warnings']


def test_selector_error_and_schema_share_supported_types():
    from simplecae.schemas import contracts
    schema_types={o['properties']['type']['const'] for o in contracts()['case']['$defs']['selector']['oneOf']}
    assert schema_types==set(SELECTOR_TYPES)
    with pytest.raises(ValueError) as error:selector({'type':'wrong'})
    assert all(t in str(error.value) for t in SELECTOR_TYPES)


def test_actual_selected_step_world_binding(tmp_path):
    step=tmp_path/'assembly.step'
    with session() as g:
        g.model.occ.addBox(0,0,0,10,20,30)
        g.model.occ.addBox(40,20,0,5,10,15)
        g.model.occ.synchronize();g.write(str(step))
    model={'path':str(step),'solid_id':{'id':2,'geometry_sha256':sha256(step)}}
    with session(step,model) as g:info=inventory(g,step)
    assert info['source_solid_count']==2 and info['source_solid_id']==2
    assert info['volume_mm3']==pytest.approx(750)
    _,m=fixture();m['frame']='world';m['provenance']['content_hash']=sha256(step)
    m['regions']['mount']={'face_count':6,'surface_types':['Plane'],
                          'faces':[{k:f[k] for k in ('area_mm2','centroid_mm')} for f in info['faces']]}
    path=tmp_path/'interfaces.json';path.write_text(json.dumps(m),encoding='utf-8')
    with session(step,{'path':str(step),'interface_manifest':str(path)}) as g:again=inventory(g,step)
    assert bind(tmp_path,m,again)['regions']['mount']==[f['id'] for f in again['faces']]


def test_occurrence_metadata_transform_is_source_bound(tmp_path):
    from simplecae.step_metadata import occurrence_placement
    payload={'component_id':'mount','definition_id':'mount','parent_definition_id':'assembly',
             'record_kind':'occurrence','placement':{'origin':[40,20,0],'x_axis':[0,1,0],'y_axis':[-1,0,0],'z_axis':[0,0,1]}}
    step=tmp_path/'metadata.step'
    step.write_text("#1=DESCRIPTIVE_REPRESENTATION_ITEM('SimpleCAD:occurrence:assembly:mount','"+json.dumps(payload)+"');",encoding='utf-8')
    label='Shapes/root/mount/part'
    assert occurrence_placement(step,label,'mount')['matrix_4x4'][0]==[0,-1,0,40]
    assert occurrence_placement(step,label,'other') is None
    info,m=fixture();info.update(source_step=str(step),source_solid_label=label,geometry_sha256=sha256(step))
    m['provenance']['content_hash']=sha256(step);del m['placement']
    assert bind(tmp_path,m,info)['placement_source']=='simplecad_step_occurrence_metadata'
    step.write_text('changed')
    with pytest.raises(ValueError,match='source changed'):bind(tmp_path,m,info)


def test_native_binding_emits_preview_and_retains_count_failure(tmp_path):
    from simplecae.region_rules import bind_regions
    step=Path(__file__).resolve().parents[1]/'examples/integration/cadgen-beam.step'
    with session(step) as g:info=inventory(g,step)
    _,m=fixture();m['frame']='world';m['part']={'solid_id':1};m['provenance']['content_hash']=sha256(step)
    m['regions']['mount']={'face_count':1,'surface_types':['Plane'],
                          'faces':[{k:info['faces'][0][k] for k in ('centroid_mm','area_mm2')}]}
    p=tmp_path/'native.json';p.write_text(json.dumps(m),encoding='utf-8')
    result=bind_regions(step,None,tmp_path/'good.json',native_manifest=p)
    assert result['preview']['selection_visible'] and Path(result['preview']['path']).is_file()
    m['regions']['mount']['face_count']=2;p.write_text(json.dumps(m),encoding='utf-8')
    with pytest.raises(WorkflowError) as error:
        bind_regions(step,None,tmp_path/'nested'/'bad.json',native_manifest=p)
    assert error.value.diagnostic['code']=='interface_face_count'
    assert Path(error.value.diagnostic['details']['inventory_preview']['path']).is_file()
    assert not (tmp_path/'nested'/'bad.json').exists()


def test_standard_step_tree_and_units(tmp_path):
    from simplecae.step_metadata import assembly_tree_placement
    source=Path(__file__).resolve().parents[1]/'examples/integration/simplecad-assembly.step'
    label='Shapes/simplecae.reference.two_bodies/right/simplecae.reference.half'
    result=assembly_tree_placement(source,label)
    assert np.asarray(result['matrix_4x4'])[:3,3]==pytest.approx([50,0,0])
    assert assembly_tree_placement(source,label.replace('/right/','/nonexistent/')) is None
    text=source.read_text(encoding='utf-8')
    inch=tmp_path/'inch.step'
    text=text.replace('SI_UNIT(.MILLI.,.METRE.)',"CONVERSION_BASED_UNIT('inch',#990)")
    text=text.replace('ENDSEC;\nEND-ISO-10303-21;',"#990=MEASURE_WITH_UNIT(LENGTH_MEASURE(0.0254),#991);\n#991=(LENGTH_UNIT() NAMED_UNIT(*) SI_UNIT($,.METRE.));\nENDSEC;\nEND-ISO-10303-21;")
    inch.write_text(text,encoding='utf-8')
    assert np.asarray(assembly_tree_placement(inch,label)['matrix_4x4'])[:3,3]==pytest.approx([1270,0,0])


def test_unrecognised_step_tree_cannot_guess_a_placement(tmp_path):
    from simplecae.step_metadata import assembly_tree_placement
    step=tmp_path/'bad.step';step.write_text('not a STEP file')
    assert assembly_tree_placement(step,'Shapes/root/child/part') is None
