"""Closed-form 2R statics and end-to-end robot failure/coverage references."""
from .defaults import DEFAULT_NATIVE_TIMEOUT
from .paths import resource_root
import json
import copy
from pathlib import Path
import math
from .case import write_json
from .robot import analyze_robot

TWO_R='''<?xml version="1.0"?>
<!-- Prescribed SI mathematical reference: masses 1 and .5 kg, link lengths
.2 and .15 m. Rod COM at half length; positive box-section inertias. -->
<robot name="two_R_reference"><link name="base"/>
<link name="upper"><inertial><origin xyz=".1 0 0"/><mass value="1"/><inertia ixx=".0000166667" iyy=".0033416667" izz=".0033416667" ixy="0" ixz="0" iyz="0"/></inertial></link>
<link name="forearm"><inertial><origin xyz=".075 0 0"/><mass value=".5"/><inertia ixx=".0000083333" iyy=".0009416667" izz=".0009416667" ixy="0" ixz="0" iyz="0"/></inertial></link>
<joint name="shoulder" type="revolute"><parent link="base"/><child link="upper"/><axis xyz="0 -1 0"/><limit lower="-3.14" upper="3.14" effort="20" velocity="1"/></joint>
<joint name="elbow" type="revolute"><parent link="upper"/><child link="forearm"/><origin xyz=".2 0 0"/><axis xyz="0 -1 0"/><limit lower="-3.14" upper="3.14" effort="8" velocity="1"/></joint></robot>'''


def validate_robots(out,ccx=None,timeout=DEFAULT_NATIVE_TIMEOUT):
    out=Path(out);out.mkdir(parents=True,exist_ok=False);inputs=out/'inputs';inputs.mkdir();checks=[];results={}
    def check(name,passed,**kw):checks.append({'name':name,'passed':bool(passed),**kw})
    def run(name,case):
        write_json(inputs/(name+'.robot.json'),case)
        r=analyze_robot(inputs/(name+'.robot.json'),out/name,ccx,timeout,True);results[name]=r;return r
    (inputs/'two-r.urdf').write_text(TWO_R,encoding='utf-8')
    conditions={k:True for k in ('inertials_verified','actuator_ratings_verified','mount_verified','poses_verified')}
    c={'schema_version':'robot-1.0','model':{'path':'two-r.urdf'},'massless_links':['base'],'poses':[{'name':n,'joints':{'shoulder':a,'elbow':b}} for n,a,b in [('extended',0,0),('folded',.4,-.8),('upright',math.pi/2,0)]],
       'gravity_m_s2':[0,0,-9.80665],'base':{'type':'fixed'},'effort_safety_factor':1.5,'conditions':conditions,
       'payloads':[{'name':'tool','link':'forearm','mass_kg':.8,'center_m':[.15,0,0]}]}
    r=run('two-r',c);check('2R posture envelope usable',r['status']=='pass_under_stated_model',error=r.get('error'))
    for pose in r['poses']:
        a=pose['joint_positions']['shoulder'];b=pose['joint_positions']['elbow']
        expected={'shoulder':9.80665*(1*.1*math.cos(a)+.5*(.2*math.cos(a)+.075*math.cos(a+b))+.8*(.2*math.cos(a)+.15*math.cos(a+b))),
                  'elbow':9.80665*(.5*.075+.8*.15)*math.cos(a+b)}
        for name,e in expected.items():check('2R/'+pose['name']+'/'+name+' closed-form effort',abs(pose['actuator_efforts'][name]['holding_effort']-e)<1e-9,expected=e)
    check('rigid statics explicitly lists unassessed link FEM',set(r.get('coverage',{}).get('links_without_fem',[]))=={'upper','forearm'})
    root=resource_root();examples=root/'examples/robots'
    base=json.loads((examples/'one-link.robot.json').read_text())
    base['model']['path']=str(examples/'one-link.urdf');base['poses']=base['poses'][:1]
    base['components'][0]['case_path']=str(examples/'arm.component.json')
    low=copy.deepcopy(base);low['effort_limits']={'shoulder':1.}
    r=run('motor-overload',low);check('motor overload fails while body passes',r['status']=='fail_under_stated_model' and r['poses'][0]['components'][0]['status']=='pass_under_stated_model')
    check('motor overload produces unfavorable margin',r['evaluation_signal']['bottleneck_margin']<1)
    scad=copy.deepcopy(base);template=json.loads((examples/'arm.component.json').read_text())
    template['model']['path']=str(root/'examples/integration/simplecad-beam.step')
    template['model']['interface_manifest']=str(root/'examples/integration/simplecad-beam.interfaces.json')
    template['supports'][0]['selector']={'type':'interface','name':'mount'}
    write_json(inputs/'simplecad.component.json',template)
    scad['components'][0]['case_path']=str(inputs/'simplecad.component.json');scad['components'][0]['ports']['tool']={'type':'interface','name':'payload'}
    r=run('simplecad-link',scad);check('native SimpleCADAPI STEP/semantic ports transfer robot loads',r['status']=='pass_under_stated_model',error=r.get('error'))
    if r['poses'] and r['poses'][0]['components']:
        transfer=r['poses'][0]['components'][0]['robot_load_transfer'];check('SimpleCAD component exact mass/COM match',transfer['com_error_mm']<.001)
    for name,mutate,word in [
        ('mass-mismatch',lambda text:text.replace('mass value="0.078"','mass value="0.1"'),'disagrees'),
        ('com-mismatch',lambda text:text.replace('xyz="0.05 0 0"/><mass value="0.078"','xyz="0.06 0 0"/><mass value="0.078"'),'COM differs')]:
        modified=inputs/(name+'.urdf');modified.write_text(mutate((examples/'one-link.urdf').read_text()).replace('assets/cadgen-beam.stl',str(examples/'assets/cadgen-beam.stl').replace('\\','/')),encoding='utf-8')
        case=copy.deepcopy(base);case['model']['path']=str(modified);r=run(name,case)
        check(name+' rejects inconsistent CAD/URDF physics',r['status']=='invalid' and word in r.get('error',''),error=r.get('error'))
        check(name+' gives no favorable signal',r['evaluation_signal']['bottleneck_margin'] is None and not r['evaluation_signal']['valid_for_comparison'])
    missing=copy.deepcopy(base);missing['poses'][0]['joints']={};r=run('missing-pose',missing)
    check('missing pose coordinate invalid',r['status']=='invalid')
    unknown=copy.deepcopy(base);unknown['components']=[];unknown['required_components']=['arm'];r=run('missing-required-fem',unknown)
    check('missing required FEM invalid',r['status']=='invalid')
    report={'passed':all(c['passed'] for c in checks),'checks':checks,'evidence_kind':'Closed-form statics plus real component solver/rejection paths; no physical robot/actuator validation.',
            'cases':{n:str((out/n/'result.json').resolve()) for n in results},'coverage':'2R and existing three-pose CAD arm, native SimpleCAD ports, actuator overload, mass/COM and required-input rejection. Mimic, prismatic, frames and friction also checked by guard tests.'}
    write_json(out/'validation.json',report);return report
