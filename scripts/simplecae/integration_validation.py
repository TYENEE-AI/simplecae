"""Actual generator exports and URDF-to-component reference verification."""
from .paths import resource_root
from pathlib import Path
import math
import numpy as np
from .case import write_json,sha256
from .workflow import analyze
from .robot import analyze_robot
from .signals import compare_results
from . import __version__
from .extended_validation import tip_mean


def validate_integration(out,ccx=None,timeout=300):
    out=Path(out);out.mkdir(parents=True,exist_ok=False)
    root=resource_root()
    fixtures=root/'examples/integration';robots=root/'examples/robots'
    models={'cadgen-step':'cadgen-beam-step.case.json','cadgen-glb':'cadgen-beam-glb.case.json',
            'cadgen-stl':'cadgen-beam-stl.case.json','cadgen-scene':'cadgen-beam-scene.case.json',
            'cadgen-thicker':'cadgen-beam-thicker-step.case.json','simplecad-native':'simplecad-beam-step.case.json'}
    results={};checks=[]
    def check(name,passed,**details):checks.append({'name':name,'passed':bool(passed),**details})
    def compare(name,actual,expected,tolerance):
        if abs(expected)<1e-12:
            error=abs(actual-expected)
            check(name,error<=1e-10,actual=actual,expected=expected,absolute_error=error,absolute_tolerance=1e-10,
                  description='Near-zero reference uses an absolute tolerance; relative error is undefined/ill-conditioned.')
            return
        error=abs(actual-expected)/max(abs(expected),1e-30)
        check(name,error<=tolerance,actual=actual,expected=expected,relative_error=error,relative_tolerance=tolerance)
    for name,case in models.items():
        r=analyze(fixtures/case,out/name,ccx,timeout,preview=True);results[name]=r
        check(name+' solves and converges',r['status']=='pass_under_stated_model',error=r.get('error'))
        if r['status']!='invalid':
            compare(name+' tip deflection',tip_mean(r,2),100*100**3/(3*200000*(10*(12 if name=='cadgen-thicker' else 10)**3/12)),.05)
            for i,l in enumerate(r['levels']):
                check(f'{name} equilibrium level {i+1}',max(l['results']['force_balance_relative_error'],l['results']['moment_balance_relative_error'])<=5e-4)
            if name=='simplecad-native':
                interface=r['levels'][-1]['mesh']['geometry'].get('interfaces',{})
                check('SimpleCAD native mount/payload roles preserved',set(interface.get('regions',{}))=={'mount','payload'})
    if all(results[n]['status']!='invalid' for n in models):
        comparison=compare_results([out/'cadgen-step/result.json',out/'cadgen-thicker/result.json'])
        write_json(out/'candidate-comparison.json',comparison)
        check('real geometry revisions comparable under shared task',comparison['comparable'])
        compare('thickness-cubed beam stiffness trend',tip_mean(results['cadgen-thicker'],2)/tip_mean(results['cadgen-step'],2),(10/12)**3,.05)
    for name,case in [('robot-arm','one-link.robot.json'),('robot-mobile','mobile-arm.robot.json'),('robot-mobile-overload','mobile-overload.robot.json')]:
        r=analyze_robot(robots/case,out/name,ccx,timeout,preview=True);results[name]=r
        expected='fail_under_stated_model' if name.endswith('overload') else 'pass_under_stated_model'
        check(name+' expected physical-model status',r['status']==expected,error=r.get('error'))
        if r['status']=='invalid':continue
        for pose in r['poses']:
            angle=pose['joint_positions']['shoulder'];payload=12 if name.endswith('overload') else 2
            compare(name+'/'+pose['name']+' holding moment',pose['actuator_efforts']['shoulder']['holding_effort'],9.80665*(.078*.05+payload*.1)*math.cos(angle),1e-8)
            for component in pose['components']:
                check(name+'/'+pose['name']+' real component FEM',component['status']=='pass_under_stated_model')
                check(name+'/'+pose['name']+' component mass and frame verified',component['robot_load_transfer']['com_error_mm']<.001)
        if name=='robot-mobile':compare('mobile static tipping multiplier',r['conditional_payload_limit']['scale_factor'],4.0585,1e-8)
        if name.endswith('overload'):
            check('ground failure despite component body passing',not r['poses'][0]['contact_equilibrium']['feasible'] and r['poses'][0]['components'][0]['status']=='pass_under_stated_model')
            check('ground failure cannot receive favorable margin',r['evaluation_signal']['bottleneck_margin'] is None and r['evaluation_signal']['feasible_under_stated_model'] is False)
    report={'passed':all(c['passed'] for c in checks),'checks':checks,'toolkit_version':__version__,
            'evidence_kind':'Numerical implementation and actual saved generator-export interoperability; no manufactured robot/material/motor validation',
            'cases':{n:str((out/n/'result.json').resolve()) for n in results},
            'fixture_sha256':{p.relative_to(root).as_posix():sha256(p) for directory in (fixtures,robots) for p in directory.rglob('*') if p.is_file() and '__pycache__' not in p.parts},
            'coverage':'STEP/GLB/STL, transformed scene, native semantic regions, geometry revision, robot poses, actual component FEM and ground equilibrium',
            'not_covered':['Explicit multi-body connection mechanics','Directional materials','Physical tests','Full product UI/release installation audit']}
    write_json(out/'validation.json',report)
    return report
