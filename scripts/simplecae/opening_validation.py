"""Native partial-opening contact reference and adverse active-count control."""
from .paths import resource_root
from pathlib import Path
import copy,json
import numpy as np
from .api import analyze_case
from .case import write_json,sha256


def validate_contact_opening(out,ccx=None,timeout=300):
    root=resource_root()
    out=Path(out).resolve();out.mkdir(parents=True,exist_ok=False)
    base=json.loads((root/'examples/mechanics/contact-partial-opening.case.json').read_text(encoding='utf-8'))
    for body in base['bodies']:body['model']['path']=str(root/'examples/mechanics/partial-opening-pad.step')
    legacy=copy.deepcopy(base);legacy['contact_control']['contact_change_relative_tolerance']=.001
    incremental=copy.deepcopy(base);incremental['contact_control'].update(initial_increment=.1,maximum_increment=.2)
    cases={'legacy-count-tolerance':legacy,'strict-count':base,'strict-incremental':incremental}
    results={};checks=[]
    def check(name,value,**details):checks.append(dict(name=name,passed=bool(value),**details))
    for name,c in cases.items():
        path=out/(name+'.case.json');write_json(path,c)
        r=analyze_case(path,out/name,ccx=ccx,timeout=timeout,preview=False,storage='full');results[name]=r
        print(name,r['status'],r.get('error',''),flush=True)
        signal=r['evaluation_signal']
        check(name+' has no installation rating',not signal['whole_installation_rating_available'])
        if name=='legacy-count-tolerance':
            diagnostic=r.get('contact_diagnostic',{})
            check('old native tolerance reproduces rejected opening spring',r['status']=='invalid' and diagnostic.get('minimum_pressure_mpa',0)<-1e-7)
            check('raw rejected points retained and located',bool(diagnostic.get('offending_samples')))
            native=diagnostic.get('native_evidence',{})
            check('rejected diagnostic binds native DAT and input',
                  native.get('dat_sha256')==sha256(Path(native['directory'])/'job.dat')
                  and native.get('input_sha256')==sha256(Path(native['directory'])/'job.inp'))
            check('negative pressure follows native linear spring on positive clearance',
                  all(s['native_clearance_mm']>0 and abs(s['nominal_linear_law_residual_mpa'])<1e-10 for s in diagnostic.get('offending_samples',[])))
            check('rejected reference cannot receive a favorable signal',not signal['valid_for_comparison'] and signal['bottleneck_margin'] is None)
        else:
            check(name+' all three meshes and complete criteria',len(r['levels'])==3 and r['status']=='pass_under_stated_model')
            for i,l in enumerate(r['levels'],1):
                m=l['results'];contact=m['contact'][0]
                check(name+f' mesh{i} unilateral pressure',contact['minimum_pressure_mpa']>=-1e-7)
                check(name+f' mesh{i} equilibrium',max(m['force_balance_relative_error'],m['moment_balance_relative_error'])<=5e-4)
                check(name+f' mesh{i} full endpoint',set(map(int,l['solver']['completed_load_steps']))=={1})
    # The tolerance A/B comparison must use the same physical discretization.
    a=np.load(out/'legacy-count-tolerance/level-02/mesh.npz')
    b=np.load(out/'strict-count/level-02/mesh.npz')
    check('same-mesh A/B isolates contact convergence control',all(np.array_equal(a[k],b[k]) for k in ('node_ids','xyz','element_ids','connectivity')))
    report={'passed':all(c['passed'] for c in checks),'checks':checks,
            'cases':{name:{'status':r['status'],'result':str(out/name/'result.json')} for name,r in results.items()},
            'scope':'Numerical partial-opening reference and rejected native-tolerance control. No physical product evidence.',
            'reference':'Two 4x10x10 mm elastic pads, E=200000 MPa, nu=0, P=1000 N and Mz=2000 Nmm; nonmatching C3D10 faces, prescribed mu=.2. Complete FE equilibrium and mesh criteria, with unchanged p>=-1e-7 MPa check.',
            'mechanism':'CCX linear face-to-face spring p=-kn*clearance on its current active set. A nonzero accepted change in active contact count can leave opening springs in the final printed state.'}
    write_json(out/'validation.json',report);return report
