"""Native1.2 workflow checks; optional real DG250 project, no hardware proof."""
from pathlib import Path
from datetime import datetime,timezone
import argparse,copy,json
import numpy as np
from simplecae import __version__
from simplecae.defaults import DEFAULT_NATIVE_TIMEOUT
from simplecae.case import load_case,sha256,write_json
from simplecae.api import analyze_case
from simplecae.schemas import check_contract
from simplecae.release import delivery_hashes
from simplecae.geometry import session,inventory
from simplecae.benchmarks import generate_examples,bar_case
from simplecae.support_presets import support_from_preset
from simplecae.task_family import analyze_gripper_task
from simplecae.interface_check import cylinder_axis,measure_interface
from simplecae.evidence import init_ledger,review_ledger
from simplecae.cache import files_digest


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True);parser.add_argument('--ccx');parser.add_argument('--timeout',type=float,default=DEFAULT_NATIVE_TIMEOUT);parser.add_argument('--project',type=Path)
    parser.add_argument('--cross-drive-task',type=Path,help='Optional actual gripper task on a different Windows drive from --out')
    a=parser.parse_args();root=Path(__file__).resolve().parents[1];out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
    snapshot=delivery_hashes(root,include_validation=False);checks=[];errors=[]
    def check(name,value,actual=None):checks.append({'name':name,'passed':bool(value),'actual':actual})
    def run(name,case,**options):
        p=out/(name+'.json');write_json(p,case)
        r=analyze_case(p,out/name,ccx=a.ccx,timeout=a.timeout,preview=False,**options);check_contract(r,'result');check_contract(r['evaluation_signal'],'signal');return r
    try:
        if a.cross_drive_task:
            cross_source=a.cross_drive_task.resolve()
            check('actual-cross-drive-source-and-output',bool(cross_source.drive) and cross_source.drive.lower()!=out.drive.lower())
            cross=analyze_gripper_task(cross_source,out/'cross-drive-family',ccx=a.ccx,timeout=a.timeout,preview=True)
            check('actual-cross-drive-public-endpoints',cross['status']=='pass_under_stated_model' and [c['normal_force_per_finger_n'] for c in cross['cases'] if c['analysis_required']]==[13,19],cross.get('error'))
            cross_manifest=json.loads((out/'cross-drive-family/compiled/force-envelope.json').read_text(encoding='utf-8'))
            check('actual-cross-drive-provenance-retained',Path(cross_manifest['source_task']).resolve()==cross_source and cross_manifest['source_task_sha256']==sha256(cross_source))
        print('Verifying task measurements, directional supports and native continuation',flush=True)
        inputs=generate_examples(out/'reference');bar=inputs/'axial.step'
        c=bar_case('axial',[1000,0,0],[5,4,3]);c['schema_version']='2.0';c['model']['path']=str(bar);c['material']['poisson_ratio']=0
        c['conditions']={n:False for n in c['conditions']};c['criteria']['max_displacement_mm']=None
        c['supports']=[support_from_preset('guide',{'type':'plane','axis':'y','position_mm':5},'sliding_guide','x'),support_from_preset('stop',{'type':'plane','axis':'x','position_mm':0},'axial_stop','x')]
        c['probes']=[{'name':'root','type':'point','point_mm':[0,0,0],'direction':[1,0,0]},
                     {'name':'middle','type':'point','point_mm':[50,0,0],'direction':[1,0,0]},
                     {'name':'tip','type':'point','point_mm':[100,0,0],'direction':[1,0,0]},
                     {'name':'extension','type':'relative','from_probe':'root','to_probe':'tip','direction':[1,0,0],'max_displacement_mm':.01}]
        first=run('guided-probes',c,reuse_levels=out/'level-cache');check('analytic-probe-only-criterion',first['status']=='pass_under_stated_model',first.get('error',first['status']))
        values={p['name']:p['value_mm'] for p in first['levels'][-1]['results']['probes']}
        check('actual-material-points-and-relative-PL-EA',all(abs(values[n]-v)<1e-6 for n,v in [('root',0),('middle',.0025),('tip',.005),('extension',.005)]),values)
        before=files_digest(out/'guided-probes');continued=copy.deepcopy(c);continued['mesh']['sizes_mm'].append(2.2)
        import simplecae.workflow as wf
        original=wf.execute;calls=[]
        def count_execute(*args,**kwargs):calls.append(str(args[1]));return original(*args,**kwargs)
        wf.execute=count_execute
        try:second=run('continued-probes',continued,reuse_levels=out/'level-cache')
        finally:wf.execute=original
        check('only-new-mesh-executed',len(calls)==1 and sum('level_reuse' in l for l in second['levels'])==3,calls)
        check('old-numerical-output-unchanged',files_digest(out/'guided-probes')==before)
        missing=copy.deepcopy(c);missing['supports']=missing['supports'][:1];invalid=run('missing-stop',missing)
        check('guide-missing-axial-stop-rejected',invalid['status']=='invalid' and 'Tx' in invalid.get('error','') and invalid['evaluation_signal']['bottleneck_margin'] is None,invalid.get('error'))
        strict=copy.deepcopy(c);strict['probes'][-1]['max_displacement_mm']=.001;failed=run('known-stiffness-failure',strict)
        check('criterion-known-failure-exposed',failed['status']=='fail_under_stated_model' and any(r['status']=='fail_under_stated_model' for r in failed['assessment']['criterion_assessments'].values()))
        bracket=load_case(inputs/'bracket.case.json');bracket['schema_version']='2.0';bracket['material']={'name':'declared6061-T6','source':'Prescribed maker hypothesis, not a stock certificate','youngs_modulus_mpa':69000,'poisson_ratio':.33,'yield_strength_mpa':240,'density_kg_m3':2700,'failure_criterion':'von_mises_yield'}
        bracket['conditions']={n:False for n in bracket['conditions']};bracket['criteria']={'yield_safety_factor':3,'max_displacement_mm':.2};bracket['gravity']={'acceleration_m_s2':[0,0,-9.80665]}
        bracket['loads'][0]['total_force_n']=[0,0,-10];bracket['provenance']={'task_id':'MAKER_CAMERA_BRACKET_10N_A'}
        demo=run('maker-camera-bracket',bracket);check('non-gripper-real-native-task',demo['status']!='invalid' and len(demo['levels'])>=3,demo.get('error',demo['status']))
        check('non-gripper-hardware-limit-withheld',not demo['assessment']['conditional_body_limit']['available'])
        print('Verifying public gripper force families and torque failure',flush=True)
        task=json.loads((root/'examples/quickstart/gripper-task.json').read_text(encoding='utf-8'));task['model_path']=str(root/'examples/quickstart/gripper.urdf')
        p=out/'gripper-task.json';write_json(p,task);family=analyze_gripper_task(p,out/'gripper-family',ccx=a.ccx,timeout=a.timeout,preview=True);check_contract(family,'task-family')
        check('one-command-force-endpoints',family['status']=='pass_under_stated_model' and [c['normal_force_per_finger_n'] for c in family['cases'] if c['analysis_required']]==[13,19],family['status'])
        check('reference-nominal-retained',family['cases'][0]['status']=='not_run')
        for entry in family['cases']:
            if not entry['analysis_required']:continue
            r=json.loads((out/'gripper-family'/entry['result_relative_path']).read_text(encoding='utf-8'))
            check(entry['name']+'/three-poses-and-no-FEM-in-quickstart',len(r['poses'])==3 and r['coverage']['component_fem_links']==[])
            check(entry['name']+'/reaction-effort-not-zeroed',all(abs(p['actuator_efforts']['slide']['holding_effort']-entry['normal_force_per_finger_n'])<1e-10 for p in r['poses']))
            check(entry['name']+'/no-physical-upgrade',not r['evaluation_signal']['physical_conditions_verified'] and not r['conditional_payload_limit']['available'])
        torsion=copy.deepcopy(task);torsion['additional_robot_loads']=[{'name':'object_twist','link':'fixed_finger','force_n':[0,0,0],'moment_n_m':[.1,0,0],'position_m':[0,0,.035],'scalable':True}];torsion['workpiece_load_names']=['object_twist']
        tp=out/'torsion-task.json';write_json(tp,torsion);twist=analyze_gripper_task(tp,out/'torsion-family',ccx=a.ccx,timeout=a.timeout,preview=False)
        check('pure-object-torque-fails-even-with-sufficient-weight-friction',twist['status']=='fail_under_stated_model',twist['status'])
        print('Verifying actual analytic hole axes and record version binding',flush=True)
        hole=out/'hole.step'
        with session() as g:
            block=g.model.occ.addBox(0,0,0,30,20,10);bore=g.model.occ.addCylinder(10,7,-1,0,0,12,3);g.model.occ.cut([(3,block)],[(3,bore)]);g.model.occ.synchronize();g.write(str(hole))
        with session(hole) as g:
            info=inventory(g,hole);face=next(f['id'] for f in info['faces'] if f['type'].lower()=='cylinder')
        reference=out/'interface-reference.txt';reference.write_text('Prescribed mathematical reference: bore center10,7mm, Zaxis, radius3mm; not a manufactured dimension record.',encoding='utf-8')
        interface={'schema_version':'simplecae-interface-1.0','model':{'path':str(hole)},'provenance':{'classification':'user_design','part_number':'mathematical-hole','source_url':'local: prescribed reference','reference_document':{'path':str(reference),'sha256':sha256(reference)},'reference_pages':[1]},
                   'checks':[{'name':'bore','type':'cylinder_axis','selector':{'type':'face_ids','ids':[face],'geometry_sha256':sha256(hole)},'expected_axis':[0,0,1],'expected_point_mm':[10,7,0],'axis_distance_tolerance_mm':.01,'angle_tolerance_deg':.01,'expected_radius_mm':3,'radius_tolerance_mm':.01}]}
        ip=out/'interface.json';write_json(ip,interface);measured=measure_interface(ip,out/'interface');data=json.loads(Path(measured['data']).read_text(encoding='utf-8'));check('native-analytic-cylinder-line-radius',data['status']=='matches_declared_reference',data['status'])
        ledger=out/'evidence.json';init_ledger([hole],ledger);l=json.loads(ledger.read_text(encoding='utf-8'));item=next(i for i in l['items'] if i['domain']=='interfaces');item.update(state='calculated',statement='Native CAD metrology only, no physical inspection')
        item['evidence']=[{'file':{'path':str(Path(measured['data'])),'sha256':sha256(Path(measured['data']))},'kind':'analytic_calculation','applies_to':['source1'],'source_sha256':{'source1':sha256(hole)},'scope':'Only the native mathematical interface check'}];write_json(ledger,l)
        er=review_ledger(ledger,out/'evidence');e=json.loads(Path(er['data']).read_text(encoding='utf-8'));check('evidence-record-snapshot-without-certification',not e['certification_available'] and bool(next(i for i in e['items'] if i['domain']=='interfaces')['evidence'][0].get('snapshot_path')))
        hole.write_bytes(hole.read_bytes()+b'\n/*test source revision*/\n');stale=review_ledger(ledger,out/'stale-evidence');s=json.loads(Path(stale['data']).read_text(encoding='utf-8'));check('changed-source-record-does-not-carry-forward',next(i for i in s['items'] if i['domain']=='interfaces')['effective_state']=='evidence_missing_or_stale')
        if a.project:
            print('Verifying actual DG250 task with force endpoints, probes and rear reaction FEM',flush=True)
            project=a.project.resolve();task=json.loads((project/'cases/gripper-task.json').read_text(encoding='utf-8'));task['model_path']=str(project/'URDF/dg250.urdf');task['task_id']='DG250_SimpleCAE1_2_endpoints_probes_paths_A'
            for component in task['components']:component['case_path']=str(project/'cases'/component['case_path'])
            task['force_measurement']={'measured_hold_interval_n':[15,17],'absolute_error_n':2,'error_verified':False,'holding_window_verified':False}
            task['grasp_model']='finite_pad_wrench';task['pad_wrench_mode']='declared_per_pad';task['grasp_conditions']['pad_contact_verified']=False
            for i,contact in enumerate(task['contacts']):
                contact['pad']={'center_link_m':[0 if i==0 else .035,0,.0575],'tangent_u_link':[0,1,0],'tangent_v_link':[0,0,1],'half_extents_m':[.008,.012]}
            task['probes']=[{'name':'fixed-contact-average','type':'surface_average','link':'fixed_finger','component_selector':{'type':'plane','axis':'x','position_mm':-1.5}},
                            {'name':'moving-contact-average','type':'surface_average','link':'moving_finger','component_selector':{'type':'plane','axis':'x','position_mm':36.5}},
                            {'name':'jaw-relative','type':'relative','from_probe':'fixed-contact-average','to_probe':'moving-contact-average','direction':[1,0,0],'max_displacement_mm':.06}]
            task['actuation_reactions']=[{'name':'linear_actuator','joint':'jaw_slide','driven':{'link':'moving_plate','point_link_m':[.061,-.022,.027]},'reaction':{'link':'rear_mount','point_link_m':[.1435,-.022,.027]},'verified':False}]
            rear=project/'STEP/rear_mount.step'
            with session(rear) as g:
                info=inventory(g,rear);ids=[]
                for f in info['faces']:
                    if f['type'].lower()!='cylinder':continue
                    axis=cylinder_axis(g,f['id'])
                    if abs(axis['radius_mm']-2.05)<1e-7 and abs(axis['point_mm'][0]-143.5)<1e-7 and abs(axis['point_mm'][2]-27)<1e-7 and abs(abs(axis['direction'][1])-1)<1e-7:ids.append(f['id'])
            port={'type':'face_ids','ids':ids,'geometry_sha256':sha256(rear)};template=load_case(project/'cases/finger_final.json');template['model']={'path':str(rear),'units':'mm'};template['loads']=[]
            template['supports']=[{'name':'declared-rear-base-seat','selector':{'type':'plane','axis':'z','position_mm':6}}];template['mesh']['sizes_mm']=[2,1.4,1];template['provenance']={'task_id':'DG006_rear_mount_body_A','model_id':'DG006','revision':'actual-rear-CAD'}
            rp=out/'DG006.case.json';write_json(rp,template);task['components'].append({'link':'rear_mount','case_path':str(rp),'ports':{'rear_actuator_pin':port,'actuation:linear_actuator:reaction':port}});task['required_components'].append('rear_mount')
            dp=out/'dg250-task.json';write_json(dp,task);dg=analyze_gripper_task(dp,out/'DG250-family',ccx=a.ccx,timeout=a.timeout,preview=True,cache=out/'DG250-complete-cache',reuse_levels=out/'DG250-level-cache')
            check_contract(dg,'task-family');check('DG250-integrated-family-not-invalid',dg['status']!='invalid',dg.get('error',dg['status']))
            for entry in dg['cases']:
                if not entry['analysis_required']:continue
                r=json.loads((out/'DG250-family'/entry['result_relative_path']).read_text(encoding='utf-8'))
                check(entry['name']+'/actual-three-component-FEM-coverage',set(r['coverage']['component_fem_links'])=={'fixed_finger','moving_finger','rear_mount'})
                for pose in r['poses']:
                    check(entry['name']+'/'+pose['name']+'/relative-jaw-measurement',pose.get('task_probe_assessment') is not None and pose['task_probe_assessment']['status']=='pass_under_stated_model')
                    check(entry['name']+'/'+pose['name']+'/rear-reaction-and-original-effort',abs(pose['actuator_efforts']['jaw_slide']['holding_effort']-(entry['normal_force_per_finger_n']+2))<1e-10 and len(pose['actuation_reaction_assessment']['pairs'])==1)
                check(entry['name']+'/physical-product-capacity-withheld',not r['conditional_payload_limit']['available'] and not r['evaluation_signal']['physical_conditions_verified'])
            initial=load_case(project/'cases/finger_initial.json');ir=run('DG250-initial-criterion-confidence',initial)
            evidence=ir['assessment']['criterion_assessments'];check('real-unresolved-strength-cannot-hide-stiffness-failure',ir['status']=='indeterminate' and evidence['stiffness']['status']=='fail_under_stated_model' and evidence['strength']['status']=='indeterminate',evidence)
    except Exception as exc:errors.append({'error':f'{type(exc).__name__}: {exc}'})
    final=delivery_hashes(root,include_validation=False);changed=[n for n in sorted(set(snapshot)|set(final)) if snapshot.get(n)!=final.get(n)]
    report={'passed':all(c['passed'] for c in checks) and bool(checks) and not errors and not changed,'toolkit_version':__version__,'recorded_at_utc':datetime.now(timezone.utc).isoformat(),
            'checks':checks,'errors':errors,'changed_sources':changed,'source_files_sha256':snapshot,'project':str(a.project.resolve()) if a.project else None,
            'scope':'Actual native mathematical/reference CAD and public workflow verification, with optional original DG250 CAD. No hardware, measured material/friction/control performance, physical acceptance or product certification.'}
    write_json(out/'usability-verification.json',report);print(json.dumps({'passed':report['passed'],'checks':len(checks),'errors':errors,'record':str(out/'usability-verification.json')}));return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
