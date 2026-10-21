"""Geometry classes and agent-loop verification, with explicit analytic scope."""
from .defaults import DEFAULT_NATIVE_TIMEOUT
from .paths import resource_root
from pathlib import Path
import copy
import math
import numpy as np
import trimesh
from .geometry import session
from .benchmarks import bar_case
from .case import write_json, sha256
from .workflow import analyze
from .extended_validation import tip_mean
from .signals import compare_results


def generate_general(out):
    out.mkdir(parents=True,exist_ok=False)
    specs={}
    with session() as g:
        outer=g.model.occ.addCylinder(0,0,0,80,0,0,10)
        inner=g.model.occ.addCylinder(0,0,0,80,0,0,6)
        g.model.occ.cut([(3,outer)],[(3,inner)])
        g.model.occ.synchronize();g.write(str(out/'tube.step'))
        g.option.setNumber('Mesh.MeshSizeMin',2.);g.option.setNumber('Mesh.MeshSizeMax',2.)
        g.model.mesh.generate(2);g.write(str(out/'tube.stl'))
    specs['tube-step']=('tube.step',80,math.pi*(100-36),[4.,3.2,2.56])
    # Generate coherent outer/inner/cap orientation explicitly. Gmsh's raw
    # surface STL export can ignore volume-boundary signs on inner cylinders.
    mesh=trimesh.creation.annulus(r_min=6.,r_max=10.,height=80.,sections=64)
    mesh.apply_transform([[0,0,1,40],[0,1,0,0],[-1,0,0,0],[0,0,0,1]])
    mesh.export(out/'tube.stl')
    area=float(mesh.volume)/80.
    specs['tube-stl']=('tube.stl',80,area,[4.,3.2,2.56])
    with session() as g:
        a=g.model.occ.addBox(0,0,0,80,10,4);b=g.model.occ.addBox(0,0,0,80,4,10)
        g.model.occ.fuse([(3,a)],[(3,b)]);g.model.occ.synchronize();g.write(str(out/'angle.step'))
        g.option.setNumber('Mesh.MeshSizeMin',2.);g.option.setNumber('Mesh.MeshSizeMax',2.)
        g.model.mesh.generate(2);g.write(str(out/'angle.stl'))
    specs['angle-step']=('angle.step',80,64.,[3.,2.4,1.92])
    specs['angle-stl']=('angle.stl',80,64.,[3.,2.4,1.92])
    # A genuinely enclosed cavity in STEP; mesh adapter intentionally requires
    # one connected boundary shell and rejects this two-shell representation.
    with session() as g:
        outer=g.model.occ.addBox(0,-10,-10,40,20,20);inner=g.model.occ.addBox(8,-6,-6,24,12,12)
        g.model.occ.cut([(3,outer)],[(3,inner)]);g.model.occ.synchronize();g.write(str(out/'housing.step'))
        g.option.setNumber('Mesh.MeshSizeMin',3.);g.option.setNumber('Mesh.MeshSizeMax',3.)
        g.model.mesh.generate(2);g.write(str(out/'housing.stl'))
    for name,(file,length,area,sizes) in specs.items():
        c=bar_case(name,[1000.,0,0],sizes);c['schema_version']='2.0'
        c['model']={'path':file};c['material']['poisson_ratio']=0.
        if file.endswith('.stl'):c['model']['units']='mm'
        c['loads'][0]['selector']['position_mm']=length
        c['notes']='Mathematical uniform axial traction, E=200000 MPa, nu=0; exact u=FL/EA, sigma_x=F/A for constant-section prism.'
        write_json(out/(name+'.case.json'),c)
    c=bar_case('housing',[100.,0,0],[4.,3.2,2.56]);c['schema_version']='2.0';c['model']={'path':'housing.step'}
    c['loads'][0]['selector']['position_mm']=40.
    write_json(out/'housing.case.json',c)
    return specs


def validate_general(out,ccx=None,timeout=DEFAULT_NATIVE_TIMEOUT):
    out=Path(out);out.mkdir(parents=True,exist_ok=False);inputs=out/'inputs';specs=generate_general(inputs)
    checks=[];results={}
    def check(name,passed,**kw):checks.append({'name':name,'passed':bool(passed),**kw})
    for name,(_,length,area,_) in specs.items():
        r=analyze(inputs/(name+'.case.json'),out/name,ccx,timeout,True);results[name]=r
        check(name+' valid converged response',r['status']=='pass_under_stated_model',error=r.get('error'))
        if r['status']=='invalid':continue
        u=tip_mean(r,0);expected=1000*length/(200000*area)
        check(name+' axial displacement',abs(u/expected-1)<.02,actual=u,expected=expected,tolerance=.02)
        for i,l in enumerate(r['levels']):
            check(f'{name} level {i+1} force/moment balance',max(l['results']['force_balance_relative_error'],l['results']['moment_balance_relative_error'])<5e-4)
            check(f'{name} level {i+1} volume conservation',abs(l['mesh']['mesh_volume_mm3']/(area*length)-1)<.02)
    r=analyze(inputs/'housing.case.json',out/'housing',ccx,timeout,True);results['housing']=r
    check('enclosed-cavity STEP produces usable elastic response',r['status']!='invalid',status=r['status'],error=r.get('error'))
    if r['status']!='invalid':
        check('enclosed-cavity STEP CAD volume',abs(r['levels'][-1]['mesh']['geometry']['volume_mm3']-(16000-3456))<1e-5)
        check('enclosed-cavity equilibrium',max(r['levels'][-1]['results']['force_balance_relative_error'],r['levels'][-1]['results']['moment_balance_relative_error'])<5e-4)
    from .mesh_input import load_surface
    try:load_surface({'path':str(inputs/'housing.stl'),'units':'mm'})
    except ValueError as exc:check('enclosed-cavity mesh rejected without repair','disconnected shells' in str(exc),reason=str(exc))
    else:check('enclosed-cavity mesh rejected without repair',False)
    root=resource_root();fixture=root/'examples/integration'
    base=json.loads((fixture/'cadgen-beam-step.case.json').read_text())
    base['model']['path']=str(fixture/'cadgen-beam.step')
    base['load_cases']=[{'name':'normal','loads':copy.deepcopy(base['loads'])},{'name':'double','loads':copy.deepcopy(base['loads'])}]
    base['load_cases'][1]['loads'][0]['total_force_n']=[0,0,-200.]
    write_json(inputs/'envelope.case.json',base)
    envelope=analyze(inputs/'envelope.case.json',out/'envelope',ccx,timeout,True);results['envelope']=envelope
    check('multi-case envelope executes both cases',len(envelope.get('cases',[]))==2 and envelope['status']=='fail_under_stated_model',status=envelope['status'])
    factors=[x['assessment']['conditional_body_limit'].get('load_pattern_scale_factor') for x in envelope.get('cases',[]) if x.get('assessment')]
    check('multi-case common limit is minimum verified case',len(factors)==2 and None not in factors and envelope.get('common_payload_scale_limit')==min(factors),factors=factors)
    if len(factors)==2 and None not in factors:check('envelope load doubling halves multiplier',abs(factors[0]/factors[1]-2)<1e-4)
    # Use the actual generator revisions; this also checks task immutability.
    candidates=[]
    for name,file in [('base','cadgen-beam-step.case.json'),('thicker','cadgen-beam-thicker-step.case.json')]:
        analyze(fixture/file,out/('candidate-'+name),ccx,timeout,True);candidates.append(out/('candidate-'+name)/'result.json')
    comparison=compare_results(candidates);write_json(out/'candidate-comparison.json',comparison)
    check('generator revisions share verified task contract',comparison['comparable'])
    signals=[x['signal'] for x in comparison['candidates']]
    check('actual thickness revision reduces deflection',signals[1]['metrics']['max_displacement_mm']<signals[0]['metrics']['max_displacement_mm'])
    changed=json.loads(candidates[1].read_text());changed['case']['loads'][0]['total_force_n']=[0,0,-50]
    from .signals import structural_contract
    changed['task_contract']=structural_contract(changed['case']);write_json(out/'changed-task.json',changed)
    check('reduced load cannot masquerade as improved design',not compare_results([candidates[0],out/'changed-task.json'])['comparable'])
    bad=copy.deepcopy(changed);bad['status']='invalid';bad['error']='reference rejected mesh';write_json(out/'invalid-candidate.json',bad)
    check('invalid candidate never ranked',not compare_results([candidates[0],out/'invalid-candidate.json'])['comparable'])
    report={'passed':all(x['passed'] for x in checks),'checks':checks,'evidence_kind':'Analytic geometry and workflow verification; housing is equilibrium/volume coverage, not an experimental strength reference.',
            'cases':{n:str((out/n/'result.json').resolve()) for n in results},'fixture_sha256':{p.name:sha256(p) for p in inputs.iterdir() if p.is_file()}}
    write_json(out/'validation.json',report);return report


import json
