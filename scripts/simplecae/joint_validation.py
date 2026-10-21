"""Analytic scalar-spring references integrated with real link FEM and gates."""
from pathlib import Path
import copy, math
import numpy as np
from .case import write_json
from .api import analyze_case


def validate_joint_compliance(out, ccx=None, timeout=300):
    from .mechanics_validation import fixtures
    out=Path(out).resolve();out.mkdir(parents=True,exist_ok=False)
    inputs=out/'inputs';_,base=fixtures(inputs)
    urdf=inputs/'two-link.urdf'
    urdf.write_text(urdf.read_text(encoding='utf-8').replace('axis xyz="0 0 1"','axis xyz="0 1 0"'),encoding='utf-8')
    base['poses']=base['poses'][:1]
    compliant=copy.deepcopy(base)
    compliant['elastic_transfer'].update(rigid_joints=['mount'],joint_compliance={'elbow':{
        'rotational_stiffness_n_m_rad':100.,'reference':'Prescribed linear torsional spring; fixed-pose mathematical reference, not measured hardware', 'verified':False}})
    bent=copy.deepcopy(compliant);bent['poses'][0]['name']='bent';bent['poses'][0]['joints']['elbow']=.6
    bent['base_pose']={'xyz_m':[.13,-.2,.3],'rpy_rad':[0,0,.7]}
    failed=copy.deepcopy(compliant);failed['probes'][0]['max_displacement_mm']=.01
    stiff=copy.deepcopy(compliant);stiff['elastic_transfer']['joint_compliance']['elbow']['rotational_stiffness_n_m_rad']=1e12
    large=copy.deepcopy(compliant);large['elastic_transfer']['joint_compliance']['elbow']['rotational_stiffness_n_m_rad']=.1
    prism=copy.deepcopy(compliant);prism['elastic_transfer']['joint_compliance']['elbow'].pop('rotational_stiffness_n_m_rad')
    prism['elastic_transfer']['joint_compliance']['elbow']['linear_stiffness_n_m']=100000.
    slider=inputs/'slider.urdf';slider.write_text(urdf.read_text(encoding='utf-8').replace('type="revolute"','type="prismatic"').replace('axis xyz="0 1 0"','axis xyz="0 0 1"'),encoding='utf-8')
    prism['model']['path']=str(slider)
    cases={'locked-reference':base,'compliant':compliant,'bent-world-frame':bent,'joint-task-failure':failed,'stiff-limit':stiff,'large-joint-motion':large,'linear-joint':prism}
    checks=[];results={}
    def check(name,passed,**data):checks.append(dict(name=name,passed=bool(passed),**data))
    for name,case in cases.items():
        path=inputs/(name+'.json');write_json(path,case)
        r=analyze_case(path,out/name,ccx=ccx,timeout=timeout,preview=True,storage='full');results[name]=r
        print(name,r['status'],r.get('error',''),flush=True)
        expected='indeterminate' if name=='large-joint-motion' else 'fail_under_stated_model' if name=='joint-task-failure' else 'pass_under_stated_model'
        check(name+' status',r['status']==expected,error=r.get('error'))
        s=r['evaluation_signal'];check(name+' numerical validity',s['valid_for_comparison']==(name!='large-joint-motion'))
        check(name+' no product or physical promotion',not s['whole_installation_rating_available'] and not s['physical_conditions_verified'])
        check(name+' no automatic chain capacity',not r.get('conditional_payload_limit',{}).get('available',False))
        from .schemas import check_contract
        check_contract(r,'result');check_contract(s,'signal');check(name+' contracts',True)
        if not r.get('poses') or not r['poses'][0].get('task_probe_assessment'):continue
        p=r['poses'][0]['task_probe_assessment']
        check(name+' whole continuum remains unassessed',not p['whole_robot_displacement_available'])
        if name=='locked-reference':continue
        e=p['elastic_transfer'];con=p['displacement_contributions']
        check(name+' separate link joint total accounting',all(np.allclose(np.array(v['link_vector_mm'])+v['joint_vector_mm'],v['total_vector_mm'],atol=1e-12) for stage in con.values() for v in stage.values()))
        if name not in ('large-joint-motion',):
            check(name+' actual mesh evidence',len(e['frame_mesh_comparisons'])>=2 and all(e['frame_mesh_comparisons'][-2:]) and e['rotation_and_warping_screens_passed'])
        if name=='large-joint-motion':
            check('excess joint rotation cannot keep favorable margin',not s['valid_for_comparison'] and s['bottleneck_margin'] is None and not e['rotation_and_warping_screens_passed'])
        if name in ('compliant','bent-world-frame','linear-joint'):
            angle=case['poses'][0]['joints']['elbow'];gravity=.039*9.80665
            for stage,tip_force in [('full',1.),('fixed',0.)]:
                record=e['joint_compliance'][stage][0]
                if name=='linear-joint':
                    expected_delta=-(tip_force+gravity)/100000.
                    vector=np.array([0,0,expected_delta*1000])
                else:
                    expected_delta=(tip_force*.05+gravity*.025)*math.cos(angle)/100.
                    yaw=case.get('base_pose',{}).get('rpy_rad',[0,0,0])[2]
                    from .robot import rotation_rpy
                    vector=rotation_rpy([0,0,yaw])@np.array([-.05*math.sin(angle),0,-.05*math.cos(angle)])*expected_delta*1000
                check(name+' '+stage+' independent scalar spring reference',abs(record['deflection']-expected_delta)<1e-12 and np.allclose(con[stage]['tip']['joint_vector_mm'],vector,atol=1e-10),actual=record['deflection'],expected=expected_delta)
        if name=='joint-task-failure':
            check('all link criteria pass while joint-inclusive task fails',all(c['status']=='pass_under_stated_model' for c in r['poses'][0]['components']) and p['criterion_assessments']['probe:tip']['status']=='fail_under_stated_model')
        if name=='stiff-limit':
            locked=results['locked-reference']['poses'][0]['task_probe_assessment']['probes'][0]['displacement_vector_mm']
            check('infinite stiffness limit approaches unchanged locked links',np.allclose(p['probes'][0]['displacement_vector_mm'],locked,atol=1e-9,rtol=1e-7))
    missing=copy.deepcopy(compliant);missing['elastic_transfer']['rigid_joints']=[]
    path=inputs/'missing-joint.json';write_json(path,missing)
    bad=analyze_case(path,out/'missing-joint',ccx=ccx,timeout=timeout,preview=False,storage='full')
    check('missing joint evidence rejects before FEM',bad['status']=='invalid' and not bad['evaluation_signal']['valid_for_comparison'] and bad['evaluation_signal']['bottleneck_margin'] is None)
    report={'passed':all(c['passed'] for c in checks),'checks':checks,'cases':{name:str(out/name/'result.json') for name in results},
            'scope':'Actual three-mesh link FEM plus independent scalar joint reference, fixed gravity, posed lever arms and adverse controls. Numerical software verification, not physical joint identification or product acceptance.'}
    write_json(out/'validation.json',report);return report
