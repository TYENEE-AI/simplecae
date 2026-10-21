"""Contact loading history and section-transfer references, with adverse controls."""
from .defaults import DEFAULT_NATIVE_TIMEOUT
from .paths import resource_root
from pathlib import Path
import copy,json,math
import numpy as np
from .case import write_json,CONDITIONS
from .api import analyze_case


def fixtures(directory):
    directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=True)
    root=resource_root();base=json.loads((root/'examples/assemblies/bonded.case.json').read_text())
    for b in base['bodies']:
        b['model']['path']=str(root/'examples/assemblies/half-bar.step')
        b['material']['calibration']={'kind':'mathematical_reference','reference':'Prescribed elastic/yield constants','applicability':'Numerical verification only; no physical material qualification'}
    base['connections'][0].update(type='frictionless_contact',normal=[1,0,0],normal_stiffness_n_mm3=100000.,
                                  calibration={'reference':'Prescribed numerical penalty law p=100000*penetration MPa','applicability':'Mathematical reference only; no hardware calibration'})
    base['supports'].append({'name':'guide','body':'right','selector':{'type':'plane','axis':'x','position_mm':0},'dofs':[2,3]})
    base['loads'][0]['total_force_n']=[-1000.,0,0]
    base['notes']='Mathematical reference only. Contact force preload is not bolt tightening or locked bolt pretension.'
    cases={'contact-compression':copy.deepcopy(base)}
    pre=copy.deepcopy(base);pre['loads'][0].update(name='preload',scalable=False)
    pre['loads'].append({'name':'service','body':'right','selector':{'type':'plane','axis':'x','position_mm':50},'total_force_n':[400,0,0]})
    cases['contact-preload']=pre
    weak=copy.deepcopy(pre)
    for b in weak['bodies']:b['material']['yield_strength_mpa']=16.
    cases['contact-preload-overload']=weak
    opened=copy.deepcopy(base);opened['supports'][-1]['selector']['position_mm']=50;opened['supports'][-1].pop('dofs')
    opened['loads'][0]['selector']['position_mm']=0;opened['loads'][0]['total_force_n']=[1000,0,0]
    cases['contact-open']=opened
    released=copy.deepcopy(opened);released['loads'][0].update(name='preload',total_force_n=[-1000,0,0],scalable=False)
    released['loads'].append({'name':'release','body':'right','selector':{'type':'plane','axis':'x','position_mm':0},'total_force_n':[2000,0,0]})
    cases['contact-release']=released
    penalty=copy.deepcopy(base);penalty['connections'][0]['normal_stiffness_n_mm3']=10000.
    penalty['connections'][0]['calibration']['reference']='Prescribed numerical penalty law p=10000*penetration MPa'
    cases['contact-softer-penalty']=penalty
    gap=copy.deepcopy(opened);gap['bodies'][1]['placement']['translation_mm'][0]=50.001
    gap['connections'][0]['initial_gap_mm']=.001;gap['loads'][0]['total_force_n']=[-1000,0,0]
    cases['contact-initial-gap']=gap
    bending=copy.deepcopy(base);bending['loads'][0]['total_moment_n_mm']=[0,0,100.]
    cases['contact-bending']=bending
    for name,case in cases.items():write_json(directory/(name+'.json'),case)
    # Two 50x10x10 mm mathematical links. Gravity stays fixed; an extra 1 N
    # tip load is scalable. Moving joints are explicitly locked at the pose.
    material=copy.deepcopy(base['bodies'][0]['material']);material['density_kg_m3']=7800.
    component={'schema_version':'2.0','model':{'path':str(root/'examples/assemblies/half-bar.step')},'material':material,
        'supports':[{'name':'upstream','selector':{'type':'plane','axis':'x','position_mm':0}}],
        'loads':[{'name':'template','selector':{'type':'plane','axis':'x','position_mm':50},'total_force_n':[0,0,-1]}],
        'criteria':{'strength_safety_factor':2.,'max_displacement_mm':.1},'mesh':{'sizes_mm':[5.,4.,3.]},'conditions':{k:True for k in CONDITIONS}}
    write_json(directory/'link.json',component)
    inertial='<inertial><origin xyz=".025 0 0"/><mass value=".039"/><inertia ixx=".00000065" iyy=".00000845" izz=".00000845" ixy="0" ixz="0" iyz="0"/></inertial>'
    urdf='<robot name="two_link_section_reference"><link name="base"/><link name="first">'+inertial+'</link><link name="second">'+inertial+'</link><joint name="mount" type="fixed"><parent link="base"/><child link="first"/></joint><joint name="elbow" type="revolute"><parent link="first"/><child link="second"/><origin xyz=".05 0 0"/><axis xyz="0 0 1"/><limit lower="-2" upper="2" effort="100" velocity="1"/></joint></robot>'
    (directory/'two-link.urdf').write_text(urdf,encoding='utf-8')
    tip={'type':'plane','axis':'x','position_mm':50}
    robot={'schema_version':'robot-1.0','model':{'path':str(directory/'two-link.urdf')},'massless_links':['base'],
        'poses':[{'name':'straight','joints':{'elbow':0.}},{'name':'right-angle','joints':{'elbow':math.pi/2}}],
        'gravity_m_s2':[0,0,-9.80665],'base':{'type':'fixed'},'conditions':{k:True for k in ('inertials_verified','actuator_ratings_verified','mount_verified','poses_verified')},
        'loads':[{'name':'tip','link':'second','force_n':[0,0,-1.],'position_m':[.05,0,0],'frame':'world','position_frame':'link'}],
        'components':[{'link':'first','case_path':str(directory/'link.json'),'ports':{'elbow':tip}},
                      {'link':'second','case_path':str(directory/'link.json'),'ports':{'tip':tip}}],
        'required_components':['first','second'],
        'probes':[{'name':'tip','type':'surface_average','link':'second','component_selector':tip,'direction':[0,0,1],'max_displacement_mm':.1}],
        'elastic_transfer':{'rigid_links':['base'],'joints_locked_verified':True,'max_rotation_rad':.01,'max_section_warping_mm':.001,
                            'reference':'Prescribed rigid locked joints, fully clamped upstream sections; numerical beam reference only.'}}
    write_json(directory/'elastic-tree.json',robot)
    return cases,robot


def validate_mechanics(out,ccx=None,timeout=DEFAULT_NATIVE_TIMEOUT):
    out=Path(out).resolve();out.mkdir(parents=True,exist_ok=False);inputs=out/'inputs';cases,robot=fixtures(inputs);checks=[];results={}
    def check(name,passed,**kw):checks.append(dict(name=name,passed=bool(passed),**kw))
    def run(name,path):
        r=analyze_case(path,out/name,ccx=ccx,timeout=timeout,preview=False,storage='full');results[name]=r;return r
    for name in cases:
        r=run(name,inputs/(name+'.json'))
        print(name,r['status'],r.get('error',''),flush=True)
        expected='fail_under_stated_model' if name=='contact-preload-overload' else 'pass_under_stated_model'
        check(name+' numerical status',r['status']==expected,error=r.get('error'))
        check(name+' public numerical validity',r['evaluation_signal']['valid_for_comparison'])
        check(name+' no linear capacity',not r.get('assessment',{}).get('conditional_body_limit',{}).get('available',False))
        check(name+' no whole installation rating',not r['evaluation_signal']['whole_installation_rating_available'])
        check(name+' reference is not physically qualified',not r['evaluation_signal']['physical_conditions_verified'])
        if not r.get('assessment'):continue
        for i,level in enumerate(r['levels']):
            check(name+f' full load and equilibrium {i}',bool(level['solver'].get('completed_load_steps')) and max(level['results']['force_balance_relative_error'],level['results']['moment_balance_relative_error'])<=5e-4)
        contact=r['levels'][-1]['results']['contact'][0]
        if name in ('contact-compression','contact-softer-penalty'):
            actual=r['levels'][-1]['results']['max_displacement_mm'];expected_u=.0051 if name=='contact-compression' else .006
            check('compression P*L/EA + P/(kn*A)',abs(actual-expected_u)/expected_u<.005,actual_mm=actual,expected_mm=expected_u)
            check('native pressure P/A',contact.get('available') and abs(contact.get('peak_pressure_mpa',0)-10)/10<.005,contact=contact)
        if 'preload' in name:
            check(name+' preload assessed separately',r.get('preload_assessment',{}).get('status')==('fail_under_stated_model' if 'overload' in name else 'pass_under_stated_model'))
            check(name+' retained preload and opposing service force',contact.get('available') and abs(contact.get('peak_pressure_mpa',0)-6)/6<.005)
            if 'overload' in name:check('service can pass while preload fails',r['assessment']['criterion_assessments']['strength']['status']=='pass_under_stated_model' and r['assessment']['criterion_assessments']['preload:strength']['status']=='fail_under_stated_model')
        if name in ('contact-open','contact-release'):
            check(name+' opened interface has no tensile pressure',contact.get('available') and contact.get('minimum_gap_mm',0)>0 and abs(contact.get('peak_pressure_mpa',1))<1e-7,contact=contact)
            if name=='contact-release':
                pre=json.loads((Path(r['levels'][-1]['directory'])/'fixed-results.json').read_text())
                check('preload closed before service opened',pre['results']['contact'][0].get('peak_pressure_mpa',0)>4.8 and r['preload_assessment']['status']=='pass_under_stated_model')
        if name=='contact-initial-gap':
            expected_p=(1000.-400.)/(2.+.04)/100.
            check('declared geometric gap closes at analytical pressure',contact.get('available') and abs(contact.get('peak_pressure_mpa',0)-expected_p)/expected_p<.005,actual=contact.get('peak_pressure_mpa'),expected=expected_p)
        if name=='contact-bending':
            check('nonuniform compression pressure follows P/A + M*y/I',contact.get('available') and abs(contact.get('peak_pressure_mpa',0)-10.6)/10.6<.02 and contact.get('minimum_pressure_mpa',0)>9.2,contact=contact,peak_reference_mpa=10.6)
    reverse=copy.deepcopy(cases['contact-compression']);reverse['connections'][0]['normal']=[-1,0,0]
    write_json(inputs/'contact-reversed-normal.json',reverse);bad=run('contact-reversed-normal',inputs/'contact-reversed-normal.json')
    check('reversed contact normal rejects with no favorable margin',bad['status']=='invalid' and 'normal' in bad.get('error','') and bad['evaluation_signal']['bottleneck_margin'] is None,error=bad.get('error'))
    r=run('elastic-tree',inputs/'elastic-tree.json');print('elastic-tree',r['status'],r.get('error',''),flush=True)
    check('two-link elastic transfer converged',r['status']=='pass_under_stated_model',error=r.get('error'))
    for pose in r.get('poses',[]):
        probe=pose.get('task_probe_assessment')
        if probe is None:continue
        full=probe['probes'][0]['signed_projection_mm'];fixed=probe['fixed_load_probes'][0]['signed_projection_mm'];actual=abs(full-fixed)
        angle=pose['joint_positions']['elbow'];length=50.;ei=200000.*10000/12;gj=100000.*.140577*10000
        expected=2*length**3/(3*ei)+length**3*(math.cos(angle)+math.cos(angle)**2)/ei+length**3*math.sin(angle)**2/gj
        # Short solid beams have shear/end corrections; this bound is declared
        # before solving and applies to the independent analytical comparison.
        check(pose['name']+' incremental beam reference including transmitted rotation/torsion',abs(actual-expected)/expected<.06,actual_mm=actual,expected_mm=expected,relative_tolerance=.06)
        check(pose['name']+' explicit approximation scope',probe['measurement_scope']=='first_order_section_frames' and not probe['whole_robot_displacement_available'])
        check(pose['name']+' no automatic chain capacity',probe['payload_scale_limit'] is None and pose['conditional_payload_scale_limit'] is None)
        if pose['name']=='straight':
            expected_g=7800*1e-9*100*9.80665*100**4/(8*ei)
            check('fixed gravity stays present in propagated chain',abs(abs(fixed)-expected_g)/expected_g<.06,actual_mm=abs(fixed),expected_mm=expected_g)
    for name,change in [('elastic-task-failure','limit'),('elastic-screen','rotation'),('elastic-world-frame','frame')]:
        case=copy.deepcopy(robot)
        case['poses']=case['poses'][:1]
        if change=='limit':case['probes'][0]['max_displacement_mm']=.0018
        elif change=='rotation':case['elastic_transfer']['max_rotation_rad']=1e-6
        else:case['base_pose']={'xyz_m':[.1,-.2,.3],'rpy_rad':[0,0,math.pi/2]}
        path=inputs/(name+'.json');write_json(path,case);extra=run(name,path)
        print(name,extra['status'],extra.get('error',''),flush=True)
        if change=='limit':
            check('independent links pass but propagated task fails',extra['status']=='fail_under_stated_model' and all(c['status']=='pass_under_stated_model' for c in extra['poses'][0]['components']))
            check('chain failure cannot have favorable signal',extra['evaluation_signal']['bottleneck_margin'] is None or extra['evaluation_signal']['bottleneck_margin']<1)
        elif change=='rotation':
            check('excess section rotation withholds verdict and margin',extra['status']=='indeterminate' and not extra['evaluation_signal']['valid_for_comparison'] and extra['evaluation_signal']['bottleneck_margin'] is None)
        elif extra.get('poses') and extra['poses'][0].get('task_probe_assessment'):
            a=extra['poses'][0]['task_probe_assessment']['probes'][0]['displacement_vector_mm'];b=r['poses'][0]['task_probe_assessment']['probes'][0]['displacement_vector_mm']
            check('translated rotated robot frame preserves actual world displacement',extra['status']=='pass_under_stated_model' and np.allclose(a,b,atol=1e-8,rtol=1e-5),actual_mm=a,reference_mm=b)
    missing=copy.deepcopy(robot);missing['elastic_transfer']['rigid_links']=[];write_json(inputs/'elastic-missing.json',missing)
    extra=run('elastic-missing',inputs/'elastic-missing.json')
    check('undeclared missing path rejects before FEM',extra['status']=='invalid' and not extra['evaluation_signal']['valid_for_comparison'] and extra['evaluation_signal']['bottleneck_margin'] is None)
    report={'passed':all(c['passed'] for c in checks),'checks':checks,'cases':{n:str(out/n/'result.json') for n in results},
            'evidence_kind':'Analytic numerical contact/loading-history/first-order-tree verification; no physical joint, bolt, friction or product qualification.',
            'references':['CalculiX 2.23 official manual: *CONTACT PAIR, *SURFACE BEHAVIOR, *STATIC, *CONTACT PRINT',
                          'Axial bar u=PL/EA + P/(kn*A), pressure=P/A','Euler-Bernoulli two-link beam energy with bending and Saint-Venant square-section torsion; fixed distributed gravity reference']}
    write_json(out/'validation.json',report);return report
