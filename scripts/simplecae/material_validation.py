"""Directional elasticity/failure reference solves and isotropic equivalence."""
from .paths import resource_root
from pathlib import Path
import copy
import numpy as np
from .benchmarks import bar_case
from .case import write_json
from .workflow import analyze
from .extended_validation import tip_mean


def reference_material():
    return {'name':'prescribed_directional','source':'Prescribed mathematical constants/strengths; not a printed-material certificate',
        'elastic_model':'orthotropic','engineering_constants':{'e1_mpa':10000.,'e2_mpa':5000.,'e3_mpa':2000.,
        'nu12':0.,'nu13':0.,'nu23':0.,'g12_mpa':2000.,'g13_mpa':1000.,'g23_mpa':800.},
        'orientation':{'axis_1':[1,0,0],'axis_2':[0,1,0]},'failure_criterion':'max_stress',
        'strengths':{'tension_mpa':[50.,25.,10.],'compression_mpa':[30.,15.,8.],'shear_mpa':[15.,10.,8.]},
        'calibration':{'kind':'mathematical_reference','reference':'Independent directional stress limits prescribed for verification',
                       'applicability':'Homogeneous mathematical box, small strain; no real product capacity'}}


def generate_material_cases(out):
    out.mkdir(parents=True,exist_ok=False)
    model=resource_root()/'examples/axial.step'
    base=bar_case('axial',[100.,0,0],[5.,4.,3.]);base['schema_version']='2.0';base['model']['path']=str(model)
    base['material']=reference_material();base['criteria']={'strength_safety_factor':2.,'max_displacement_mm':.4}
    cases={}
    cases['axis-1']=copy.deepcopy(base)
    cases['axis-2']=copy.deepcopy(base);cases['axis-2']['material']['orientation']={'axis_1':[0,1,0],'axis_2':[-1,0,0]}
    cases['axis-3']=copy.deepcopy(base);cases['axis-3']['material']['orientation']={'axis_1':[0,1,0],'axis_2':[0,0,1]}
    cases['compression']=copy.deepcopy(base);cases['compression']['loads'][0]['total_force_n']=[-100,0,0]
    cases['rotated-45']=copy.deepcopy(base);q=2**-.5;cases['rotated-45']['material']['orientation']={'axis_1':[q,q,0],'axis_2':[-q,q,0]}
    iso=bar_case('axial',[100,0,0],[5,4,3]);iso['schema_version']='2.0';iso['model']['path']=str(model)
    cases['isotropic']=iso;eq=copy.deepcopy(iso);eq['material']=reference_material()
    e=200000.;n=.3;g=e/(2*(1+n));eq['material']['engineering_constants']={k:v for k,v in zip(eq['material']['engineering_constants'],[e,e,e,n,n,n,g,g,g])}
    q=2**-.5;eq['material']['orientation']={'axis_1':[q,q,0],'axis_2':[-q,q,0]};cases['isotropic-limit']=eq
    for name,c in cases.items():write_json(out/f'{name}.case.json',c)
    return cases


def validate_materials(out,ccx=None,timeout=300):
    out=Path(out);out.mkdir(parents=True,exist_ok=False);cases=generate_material_cases(out/'inputs');results={};checks=[]
    def check(name,passed,**detail):checks.append({'name':name,'passed':bool(passed),**detail})
    def compare(name,a,b,tol):
        error=abs(a-b)/max(abs(b),1e-30);check(name,error<=tol,actual=a,expected=b,relative_error=error,relative_tolerance=tol)
    for name,c in cases.items():
        r=analyze(out/'inputs'/f'{name}.case.json',out/name,ccx,timeout,preview=True);results[name]=r
        check(name+' complete converged solve',r['status']=='pass_under_stated_model',error=r.get('error'))
        if r['status']=='invalid':continue
        modulus={'axis-1':10000.,'axis-2':5000.,'axis-3':2000.,'compression':10000.,'rotated-45':5000.,'isotropic':200000.,'isotropic-limit':200000.}[name]
        compare(name+' axial mean deflection',tip_mean(r,0),100*100/(100*modulus),.05)
        for i,l in enumerate(r['levels']):check(f'{name} force/moment balance {i+1}',max(l['results']['force_balance_relative_error'],l['results']['moment_balance_relative_error'])<5e-4)
        if name in ('axis-1','axis-2','axis-3','compression'):
            expected={'axis-1':25.,'axis-2':12.5,'axis-3':5.,'compression':15.}[name]
            limit=r['assessment']['conditional_body_limit'];check(name+' conditional directional limit available',limit['available'])
            if limit['available']:compare(name+' signed directional limit',limit['load_pattern_scale_factor'],expected,.01)
    if all(results[n]['status']!='invalid' for n in ('isotropic','isotropic-limit')):
        def fields(name):return np.load(Path(results[name]['levels'][-1]['directory'])/'fields.npz')
        a,b=fields('isotropic'),fields('isotropic-limit')
        check('isotropic-equivalent mesh ordering identical',np.array_equal(a['stress_ids'],b['stress_ids']) and np.array_equal(a['node_ids'],b['node_ids']))
        for key in ('displacements','stresses','strains'):
            error=float(np.max(np.abs(a[key]-b[key]))/max(np.max(np.abs(a[key])),1e-30))
            check('rotated isotropic-equivalence '+key,error<1e-4,relative_field_error=error,relative_tolerance=1e-4)
    proof={'passed':all(c['passed'] for c in checks),'checks':checks,'evidence_kind':'Directional/isotropic-limit numerical verification; no material coupon or manufactured product validation',
           'cases':{n:str((out/n/'result.json').resolve()) for n in results},
           'sources':['CalculiX 2.23 ELASTIC/ORIENTATION/EL PRINT GLOBAL documentation','Orthotropic compliance reciprocity and positive energy','Uniform axial u=PL/(EA); transformed compliance Sxxxx at 45 degrees']}
    write_json(out/'validation.json',proof);return proof
