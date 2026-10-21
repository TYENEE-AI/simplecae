"""Small real-solver examples of pass, failure and insufficient evidence."""
from .paths import resource_root
from pathlib import Path
import json
from .case import write_json
from .schemas import check_contract
from .signals import compare_results
from .workflow import analyze


def run_quickstart(out, example='pass', ccx=None, timeout=300, progress=None):
    root=resource_root()
    fixtures=root/'examples/preview'
    manifest=json.loads((fixtures/'examples.json').read_text(encoding='utf-8'))
    out=Path(out).resolve();out.mkdir(parents=True,exist_ok=False)
    names=list(manifest) if example=='all' else [example]
    checks=[];reports={}
    for name in names:
        spec=manifest[name]
        result=analyze(fixtures/spec['case'],out/name,ccx,timeout,True,progress=progress)
        check_contract(result,'result');check_contract(result['evaluation_signal'],'signal')
        signal=result['evaluation_signal']
        passed=(result['status']==spec['expected_status'] and not signal['whole_installation_rating_available']
                and not signal['physical_conditions_verified'] and not (signal.get('conditional_limit') or {}).get('available'))
        if name=='indeterminate':
            passed=passed and not signal['valid_for_comparison'] and signal['bottleneck_margin'] is None and not signal['conditional_limit']['available']
        checks.append({'example':name,'status':result['status'],'expected_status':spec['expected_status'],
                       'passed':bool(passed),'report':f'{name}/report.html','meaning':spec['meaning']})
        reports[name]=str(out/name/'report.html')
    if example=='all':
        comparison=compare_results([out/'fail/result.json',out/'iteration/result.json'])
        check_contract(comparison,'comparison');write_json(out/'candidate-comparison.json',comparison)
        checks.append({'example':'same-task-iteration','passed':comparison['comparable'],
                       'meaning':'Only geometry changes; material, mounting, load, displacement limit and quality gates stay fixed.'})
    report={'passed':all(c['passed'] for c in checks),'checks':checks,
            'meaning':'Expected example behavior checked with real Gmsh/CalculiX runs. This is not product acceptance or a safe working load.',
            'reports':reports}
    write_json(out/'quickstart.json',report)
    return report
