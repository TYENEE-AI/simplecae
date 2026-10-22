"""Regenerate SimpleCAE-authored mathematical fixtures, not catalog or user CAD."""
from pathlib import Path
import copy
from simplecae.benchmarks import bar_case
from simplecae.case import write_json
from simplecae.geometry import session


def generate(out):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    with session() as g:
        g.model.occ.addBox(0,-5,-5,100,10,10);g.model.occ.synchronize();g.write(str(out/'beam.step'))
        g.clear();g.model.add('wide')
        g.model.occ.addBox(0,-10,-5,100,20,10);g.model.occ.synchronize();g.write(str(out/'beam-wide.step'))
    base=bar_case('beam',[0,0,-100],[5,4,3]);base['schema_version']='2.0'
    base['conditions']={k:False for k in base['conditions']}
    base['notes']='SimpleCAE-authored mathematical example. All physical verification flags stay false. Ideal full clamp and uniform face force; gravity, fasteners and manufacturing are not evaluated.'
    base['provenance']={'task_id':'preview-beam-100N'}
    write_json(out/'pass.case.json',base)
    failed=copy.deepcopy(base);failed['loads'][0]['total_force_n']=[0,0,-200]
    failed['provenance']['task_id']='preview-beam-200N';write_json(out/'fail.case.json',failed)
    missing=copy.deepcopy(base);missing['material'].pop('yield_strength_mpa')
    missing['material']['failure_criterion']='not_specified'
    missing['material']['source']='Elastic constants are mathematical assumptions; no strength value or applicable failure criterion has been supplied.'
    write_json(out/'indeterminate.case.json',missing)
    wider=copy.deepcopy(failed);wider['model']={'path':'beam-wide.step','expected_bbox_mm':[[0,-10,-5],[100,10,5]]}
    write_json(out/'iteration.case.json',wider)
    write_json(out/'examples.json',{
        'pass':{'case':'pass.case.json','expected_status':'pass_under_stated_model','meaning':'100 N, declared strength and 0.3 mm displacement criteria pass numerically. No physical qualification.'},
        'fail':{'case':'fail.case.json','expected_status':'fail_under_stated_model','meaning':'200 N, same strength and 0.3 mm criteria: converged displacement exceeds its limit.'},
        'indeterminate':{'case':'indeterminate.case.json','expected_status':'indeterminate','meaning':'100 N elastic solution, but strength data/failure criterion missing. Do not rank or issue capacity.'},
        'iteration':{'case':'iteration.case.json','expected_status':'pass_under_stated_model','meaning':'200 N, width increased from 10 to 20 mm; same task physics and criteria as fail. Numerical improvement only.'}})


if __name__=='__main__':generate(Path(__file__).resolve().parent)
