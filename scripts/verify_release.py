"""Reproduce all numerical suites and public output contracts; no physical certification."""
from pathlib import Path
import argparse
import json
import importlib.metadata
import platform
import os
import sys
import subprocess
from datetime import datetime,timezone
from simplecae import __version__
from simplecae.defaults import DEFAULT_NATIVE_TIMEOUT
from simplecae.case import sha256,write_json
from simplecae.benchmarks import validate_benchmarks
from simplecae.extended_validation import validate_extended
from simplecae.material_validation import validate_materials
from simplecae.assembly_validation import validate_assemblies
from simplecae.integration_validation import validate_integration
from simplecae.general_validation import validate_general
from simplecae.robot_validation import validate_robots
from simplecae.maker_validation import validate_maker
from simplecae.mechanics_validation import validate_mechanics
from simplecae.bolt_friction_validation import validate_bolt_friction
from simplecae.joint_validation import validate_joint_compliance
from simplecae.footprint_validation import validate_footprints
from simplecae.opening_validation import validate_contact_opening
from simplecae.design_validation import validate_design_checks
from simplecae.release import delivery_hashes


def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--ccx');p.add_argument('--timeout',type=float,default=DEFAULT_NATIVE_TIMEOUT)
    p.add_argument('--regression-timeout',type=float,default=1800,help='Configurable wall-clock cap for the full current test suite')
    a=p.parse_args()
    import math
    if not all(math.isfinite(v) and v>0 for v in (a.timeout,a.regression_timeout)):
        p.error('timeouts must be finite and positive')
    out=a.out.resolve();out.mkdir(parents=True,exist_ok=False);root=Path(__file__).resolve().parents[1]
    snapshot=delivery_hashes(root,include_validation=False)
    reports={};errors=[]
    for name,fn in [('standard',validate_benchmarks),('extended',validate_extended),('materials',validate_materials),('assemblies',validate_assemblies),('integration',validate_integration),('general',validate_general),('robots',validate_robots),('maker',validate_maker),('mechanics',validate_mechanics),('bolt-friction',validate_bolt_friction),('joint-compliance',validate_joint_compliance),('planar-footprints',validate_footprints),('contact-opening',validate_contact_opening),('design-checks',validate_design_checks)]:
        print('Verifying '+name,flush=True)
        try:
            r=fn(out/name,a.ccx,a.timeout)
            try:record=Path(os.path.relpath(out/name/'validation.json',root)).as_posix()
            except ValueError:record=str(out/name/'validation.json')
            reports[name]={'passed':r['passed'],'checks':len(r.get('checks',[])),'record':record,'sha256':sha256(out/name/'validation.json')}
        except Exception as exc:
            errors.append({'suite':name,'error':str(exc)});reports[name]={'passed':False,'checks':0}
        print(json.dumps({name:reports[name]}),flush=True)
    # Legacy native suites predate thermal/modal/motion/durability. Require the
    # full current suite and explicit family coverage, never infer it from an
    # old release receipt or a green test process with zero relevant tests.
    print('Verifying current physics and Agent workflow regression',flush=True)
    from simplecae.execution import run_owned_worker
    from simplecae.release_checks import regression_coverage
    regression_xml=out/'regression.xml'
    environment=os.environ.copy()
    if a.ccx:
        from simplecae.solver import find_ccx
        environment['SIMPLECAE_CCX']=str(find_ccx(a.ccx))
    try:
        with (out/'regression.log').open('w',encoding='utf8') as log:
            completed=run_owned_worker([sys.executable,'-m','pytest',str(root/'tests'),'-q',
                '--junitxml='+str(regression_xml),'--basetemp='+str(out/'pytest-tmp')],
                timeout=a.regression_timeout,env=environment,stdout=log,stderr=subprocess.STDOUT,cwd=root)
        regression=regression_coverage(regression_xml,completed.returncode)
        write_json(out/'regression-coverage.json',regression)
        reports['current-physics-and-workflow']={'passed':regression['passed'],'checks':regression['tests'],
            'record':str(out/'regression-coverage.json'),'sha256':sha256(out/'regression-coverage.json'),
            'required_module_coverage':regression['required_module_coverage']}
    except Exception as exc:
        errors.append({'suite':'current-physics-and-workflow','error':str(exc)})
        reports['current-physics-and-workflow']={'passed':False,'checks':0}
    from simplecae.release_checks import native_output_contracts
    count,contract_errors=native_output_contracts(out,[name for name in reports if name!='current-physics-and-workflow'])
    errors.extend(contract_errors)
    final_snapshot=delivery_hashes(root,include_validation=False)
    changed=[name for name in sorted(set(snapshot)|set(final_snapshot)) if snapshot.get(name)!=final_snapshot.get(name)]
    report={'passed':all(r['passed'] for r in reports.values()) and not errors and not changed,'toolkit_version':__version__,
        'recorded_at_utc':datetime.now(timezone.utc).isoformat(),'platform':platform.platform(),'python':platform.python_version(),
        'suites':reports,'numerical_checks':sum(r['checks'] for r in reports.values()),'output_contract_checks':count,'errors':errors,'changed_sources':changed,
        'runtime_versions':{n:importlib.metadata.version(n) for n in ('gmsh','numpy','scipy','matplotlib','trimesh','manifold3d','meshio','defusedxml','jsonschema')},
        'source_files_sha256':snapshot,'evidence_kind':'Analytic numerical, source/format/SDK interoperability and software contracts; no physical product/material/hardware validation.'}
    write_json(out/'verification.json',report);print(json.dumps({'passed':report['passed'],'record':str(out/'verification.json')}));return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
