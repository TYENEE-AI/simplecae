"""Independent axial-joint and displacement-controlled Coulomb references.

The fixtures prescribe mathematical materials and ideal fixtures. They verify
the numerical method, not a physical bolted product or a measured friction law.
"""
from .defaults import DEFAULT_NATIVE_TIMEOUT
from pathlib import Path
import copy
import math
from .case import write_json
from .api import analyze_case


def fixtures(directory):
    from .mechanics_validation import fixtures as mechanics_fixtures
    directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=True)
    prior,_=mechanics_fixtures(directory/'legacy-inputs')
    base=copy.deepcopy(prior['contact-compression'])
    base['notes']='Mathematical reference only; explicit axial bolt, ideal fixtures and prescribed planar contact law. No physical product qualification.'
    base['loads'][0]['total_force_n']=[200.,0,0]
    base['bolts']=[{'name':'tie','master':{'body':'left','selector':{'type':'plane','axis':'x','position_mm':0}},
        'slave':{'body':'right','selector':{'type':'plane','axis':'x','position_mm':50}},'axis':[1,0,0],
        'axial_stiffness_n_mm':100000.,'preload_n':1000.,'allowable_tension_n':2000.,
        'reference':'Prescribed mathematical spring k=100000 N/mm; preload=1000 N; axial allowable=2000 N (already includes the chosen safety allowance). No torque inference.'}]
    cases={'bolt-locked':base}
    other=copy.deepcopy(base);other['bolts'][0].update(axial_stiffness_n_mm=50000.,preload_n=600.,reference='Different prescribed mathematical fastener: k=50000 N/mm, P0=600 N, allowable=2000 N.');other['loads'][0]['total_force_n']=[150.,0,0];cases['bolt-different-stiffness']=other
    pure=copy.deepcopy(base);pure['loads']=[];cases['bolt-preload-only']=pure
    weak=copy.deepcopy(base);weak['bolts'][0]['allowable_tension_n']=1050.;cases['bolt-overload']=weak
    pre=copy.deepcopy(base);pre['loads'][0]['total_force_n']=[-200.,0,0];pre['bolts'][0]['allowable_tension_n']=980.;cases['bolt-preload-overload']=pre
    # Same physics in a translated, rotated world frame with different names.
    rotated=copy.deepcopy(base)
    for b in rotated['bodies']:
        p=b.setdefault('placement',{});t=p.get('translation_mm',[0,0,0])
        p.update(translation_mm=[17-t[1],-23+t[0],11+t[2]],rpy_rad=[0,0,math.pi/2])
    rotated['loads'][0]['total_force_n']=[0,200.,0];rotated['supports'][1]['dofs']=[1,3]
    rotated['connections'][0]['normal']=[0,1,0];rotated['bolts'][0].update(name='axial-fastener',axis=[0,1,0])
    for field in ('supports','loads'):
        for item in rotated[field]:item['body']={'left':'housing','right':'cap'}[item['body']]
    for obj in rotated['connections']+rotated['bolts']:
        for role in ('master','slave'):obj[role]['body']={'left':'housing','right':'cap'}[obj[role]['body']]
    for b in rotated['bodies']:b['name']={'left':'housing','right':'cap'}[b['name']]
    cases['bolt-world-frame']=rotated
    # Ideal test rig controls both contact faces tangentially. Normal compression
    # is applied at the remote end. Thus actual material motion is prescribed,
    # pressure=P/A and shear=min(kt*motion, mu*P/A), independent of solver output.
    friction=copy.deepcopy(prior['contact-compression'])
    friction['loads'][0]['scalable']=False
    friction['supports'].append({'name':'master-tangential-guide','body':'left','selector':{'type':'plane','axis':'x','position_mm':50},'dofs':[2,3]})
    friction['supports'][1]['service_displacement_mm']=[0,.00005,0]
    friction['connections'][0].update(type='frictional_contact',friction_coefficient=.2,
        tangential_stiffness_n_mm3=10000.,max_tangential_displacement_mm=.001,
        calibration={'reference':'Prescribed Coulomb law tau=min(kt*delta,mu*p); kn=100000, kt=10000 N/mm^3, mu=.2.',
                     'applicability':'Mathematical displacement-controlled planar rig only; no measured interface calibration.'})
    cases['friction-stick']=friction
    sliding=copy.deepcopy(friction);sliding['supports'][1]['service_displacement_mm']=[0,.002,0];cases['friction-motion-failure']=sliding
    other=copy.deepcopy(sliding);other['connections'][0].update(friction_coefficient=.35,tangential_stiffness_n_mm3=5000.);other['connections'][0]['calibration']['reference']='Different prescribed Coulomb law: mu=.35, kt=5000 N/mm^3.';cases['friction-different-law-failure']=other
    force=copy.deepcopy(friction);force['supports']=force['supports'][:2]
    force['supports'][1].update(selector={'type':'plane','axis':'z','position_mm':5},dofs=[3]);force['supports'][1].pop('service_displacement_mm')
    force['loads'].append({'name':'service-shear','body':'right','selector':{'type':'plane','axis':'x','position_mm':0},'total_force_n':[0,100.,0]})
    force['notes']='Adverse force-controlled reference. No tangential guide bypasses friction. Zero-shear preload peak may remain unresolved on these meshes; do not discard it because service converges.'
    cases['friction-force-controlled']=force
    combined=copy.deepcopy(base)
    combined['supports'].append(copy.deepcopy(friction['supports'][-1]));combined['supports'][1]['service_displacement_mm']=[0,.00005,0]
    combined['connections'][0].update({k:v for k,v in friction['connections'][0].items() if k not in ('master','slave','name')})
    cases['bolt-friction-combined']=combined
    ramp=copy.deepcopy(combined)
    ramp['contact_control']={'initial_increment':1.,'maximum_increment':1.,
                            'service_initial_increment':.1,'service_maximum_increment':.2}
    cases['bolt-friction-service-ramp']=ramp
    opened=copy.deepcopy(base);opened['loads'][0]['selector']['position_mm']=0;opened['loads'][0]['total_force_n']=[2000.,0,0]
    opened['supports'][1]['selector']['position_mm']=50;opened['bolts'][0]['allowable_tension_n']=2500.;cases['bolt-separated']=opened
    for name,case in cases.items():write_json(directory/(name+'.json'),case)
    write_json(directory/'reference.json',{'scope':'Numerical reference, not product evidence',
        'axial':{'k_b_n_mm':100000.,'k_c_n_mm':1/(100/(200000*100)+1/(100000*100)),
                 'formula':'C=kb/(kb+kc); Fbolt=P0+C*P; Fclamp=P0-(1-C)*P; q0=P0/kb+P0/kc',
                 'relative_tolerance':.005},
        'friction':{'formula':'p=P/A; tau=min(kt*delta,mu*p)', 'relative_tolerance':.005,
                    'motion_absolute_tolerance_mm':1e-8,
                    'fixture':'Both interface faces tangentially guided; only slave guide translates in service. Normal direction is free on guides.'}})
    return cases


def validate_bolt_friction(out,ccx=None,timeout=DEFAULT_NATIVE_TIMEOUT):
    out=Path(out).resolve();out.mkdir(parents=True,exist_ok=False);inputs=out/'inputs';cases=fixtures(inputs);checks=[];results={}
    def check(name,passed,**kw):checks.append(dict(name=name,passed=bool(passed),**kw))
    for name,case in cases.items():
        r=analyze_case(inputs/(name+'.json'),out/name,ccx=ccx,timeout=timeout,preview=False,storage='full');results[name]=r
        print(name,r['status'],r.get('error',''),flush=True)
        expected='indeterminate' if name=='friction-force-controlled' else 'fail_under_stated_model' if name in ('bolt-overload','bolt-preload-overload') or name.endswith('failure') else 'pass_under_stated_model'
        check(name+' model verdict',r['status']==expected,error=r.get('error'))
        signal=r['evaluation_signal']
        check(name+' numerical evidence not promoted',not signal['valid_for_comparison'] and signal['bottleneck_margin'] is None) if name=='friction-force-controlled' else check(name+' complete numerical evidence',signal['valid_for_comparison'])
        check(name+' no physical product qualification',not signal['physical_conditions_verified'] and not signal['whole_installation_rating_available'])
        check(name+' no contact capacity extrapolation',not r.get('assessment',{}).get('conditional_body_limit',{}).get('available',False))
        if not r.get('assessment'):continue
        for i,level in enumerate(r['levels']):
            check(name+f' force and moment balance {i}',max(level['results']['force_balance_relative_error'],level['results']['moment_balance_relative_error'])<=5e-4)
            check(name+f' all stages completed {i}',set(map(int,level['solver']['completed_load_steps']))==set(range(1,4 if case.get('bolts') else 3)))
        actual=r['levels'][-1]['results'];criteria=r['assessment']['criterion_assessments']
        if case.get('bolts'):
            kc=1/(100/(200000*100)+1/(100000*100));kb=case['bolts'][0]['axial_stiffness_n_mm'];p0=case['bolts'][0]['preload_n'];c=kb/(kb+kc)
            p=case['loads'][0]['total_force_n'][1 if name=='bolt-world-frame' else 0] if case['loads'] else 0.
            expected_force=p0+c*p;expected_pressure=(p0-(1-c)*p)/100;q0=p0/kb+p0/kc
            if name=='bolt-separated':expected_force=p;expected_pressure=0.
            b=actual['bolts'][0]
            check(name+' independent two-spring bolt force',abs(b['force_n']-expected_force)/expected_force<.005,actual_n=b['force_n'],reference_n=expected_force)
            check(name+' independent retained clamping pressure',abs(actual['contact'][0]['peak_pressure_mpa']-expected_pressure)/max(expected_pressure,1e-8)<.005,actual_mpa=actual['contact'][0]['peak_pressure_mpa'],reference_mpa=expected_pressure)
            check(name+' locked adjustment q0',b['locked'] and b['lock_error_mm']<=1e-9 and abs(b['adjustment_mm']-q0)/q0<.005,actual_mm=b['adjustment_mm'],reference_mm=q0)
            check(name+' preload and lock assessed',all(r['stage_assessments'][s]['verification']['mesh_converged'] for s in ('preload','locked')))
            if name=='bolt-preload-overload':check('service bolt passes but preload failure remains',criteria['bolt:tie']['status']=='pass_under_stated_model' and criteria['preload:bolt:tie']['status']=='fail_under_stated_model')
            if name=='bolt-overload':check('body strength passes while bolt fails',criteria['strength']['status']=='pass_under_stated_model' and criteria['bolt:tie']['status']=='fail_under_stated_model')
            if name=='bolt-separated':
                # After separation the spring alone balances P, while the right
                # bar is compressed between its loaded inner face and bolt end.
                check('open joint: bolt carries external force',abs(b['force_n']-p)/p<.005)
                check('open joint: no tensile contact pressure',actual['contact'][0]['minimum_gap_mm']>0 and actual['contact'][0]['peak_pressure_mpa']==0)
            if name=='bolt-friction-service-ramp':
                contact=actual['contact'][0]
                check('service-only ramp retains analytic sticking shear',abs(contact['peak_shear_mpa']-.5)/.5<.005)
                check('service-only ramp reaches prescribed motion',abs(contact['peak_tangential_displacement_mm']-.00005)<1e-8)
                check('service-only ramp uses multiple full-endpoint increments',
                      all(l['solver']['completed_load_steps'][3]['increment']>1 for l in r['levels']))
        if name=='friction-force-controlled':
            check('force-controlled service converges but preload shear remains unresolved',r['assessment']['verification']['mesh_converged'] and not r['preload_assessment']['verification']['mesh_converged'])
            check('force-controlled contact has no tangential fixture bypass',all(2 not in s.get('dofs',[1,2,3]) for s in case['supports'] if s['body']=='right'))
        elif name.startswith('friction-'):
            p=actual['contact'][0];delta=case['supports'][1]['service_displacement_mm'][1]
            spec=case['connections'][0];tau=min(spec['tangential_stiffness_n_mm3']*delta,spec['friction_coefficient']*10)
            check(name+' independent pressure',abs(p['peak_pressure_mpa']-10)/10<.005,actual_mpa=p['peak_pressure_mpa'])
            check(name+' independent Coulomb shear',abs(p['peak_shear_mpa']-tau)/tau<.005,actual_mpa=p['peak_shear_mpa'],reference_mpa=tau)
            check(name+' actual relative material motion',abs(p['peak_tangential_displacement_mm']-delta)<1e-8,actual_mm=p['peak_tangential_displacement_mm'],reference_mm=delta)
            check(name+' Coulomb bound and small sliding',p['coulomb_bound_passed'] and p['small_sliding_screen_passed'])
            check(name+' stick or sliding state',p['sliding_sample_count']==0 if name=='friction-stick' else p['sliding_sample_count']>0)
            if name=='friction-motion-failure':check('body criteria pass while motion fails',all(criteria[k]['status']=='pass_under_stated_model' for k in ('strength','stiffness')) and criteria['contact_motion:joint']['status']=='fail_under_stated_model')
    for name,change in [('missing-friction-calibration','calibration'),('negative-bolt-stiffness','stiffness'),('unsupported-bolt-axis','axis'),('conflicting-fixture-motion','fixture'),('excess-contact-motion','motion')]:
        case=copy.deepcopy(cases['friction-stick'] if change in ('calibration','motion','fixture') else cases['bolt-locked'])
        if change=='calibration':case['connections'][0].pop('calibration')
        elif change=='stiffness':case['bolts'][0]['axial_stiffness_n_mm']=-1
        elif change=='axis':case['bolts'][0]['axis']=[0,1,0]
        elif change=='fixture':
            s=copy.deepcopy(case['supports'][1]);s['name']='stationary-conflicting-guide';s.pop('service_displacement_mm');case['supports'].append(s)
        else:case['supports'][1]['service_displacement_mm']=[0,.15,0]
        path=inputs/(name+'.json');write_json(path,case)
        try:r=analyze_case(path,out/name,ccx=ccx,timeout=timeout,preview=False,storage='full')
        except Exception as exc:
            # The typed API rejects malformed cases before creating a result.
            # Record an input guard, never fabricate a solved/invalid FEM job.
            expected_error={'calibration':'sources','stiffness':'$.bolts[0].axial_stiffness_n_mm: -1 is less than or equal to the minimum of 0'}.get(change)
            check(name+' input rejected before solve',bool(expected_error and expected_error in str(exc)) and not (out/name).exists(),error=f'{type(exc).__name__}: {exc}',evidence_kind='input rejection, not a native FEM solve')
            continue
        results[name]=r
        print(name,r['status'],r.get('error',''),flush=True)
        check(name+' rejects or withholds favorable verdict',r['status'] in (('invalid','indeterminate') if change=='motion' else ('invalid',)) and not r['evaluation_signal']['valid_for_comparison'] and r['evaluation_signal']['bottleneck_margin'] is None,error=r.get('error'))
    report={'passed':all(c['passed'] for c in checks),'checks':checks,'cases':{n:str(out/n/'result.json') for n in results},
        'evidence_kind':'Mathematical axial-joint/Coulomb-law and staged failure verification; no physical bolt, friction or product qualification.',
        'references':['Two parallel axial stiffnesses with retained interference q0: kb*(delta+q0), compressed member/penalty stiffness kc.',
            'Planar Coulomb law with explicitly controlled material motion: p=P/A, tau=min(kt*delta,mu*p).',
            'CalculiX 2.23 manual: *BOUNDARY,FIXED, *SPRING, *EQUATION, *FRICTION, *CONTACT PRINT.']}
    write_json(out/'validation.json',report);return report
