"""Re-run demonstrated audit scenarios with real meshes/statics/eigen solves."""
from pathlib import Path
import argparse
import copy
import json
from simplecae import __version__
from simplecae.case import load_case,sha256,write_json
from simplecae.geometry import make_mesh
from simplecae.workflow import analyze
from simplecae.robot import load_robot_case,analyze_robot
from simplecae.signals import compare_results,design_signal
from simplecae.schemas import check_contract


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--verification',type=Path,required=True)
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=False)
    root=Path(__file__).resolve().parents[1];checks=[]
    def check(name,passed,**details):
        checks.append(dict(name=name,passed=bool(passed),**details))
        print(json.dumps(checks[-1]),flush=True)
    column=load_case(root/'examples/advanced/column.case.json')
    column['loads'][0]['total_force_n']=[-3000.,0,0]
    column['load_cases']=[{'name':'compression','loads':copy.deepcopy(column['loads'])}]
    path=out/'buckling-envelope.case.json';write_json(path,column)
    solved=analyze(path,out/'buckling-envelope',preview=True)
    signal=solved['evaluation_signal'];assessment=solved['cases'][0].get('assessment') or {}
    check('F1 real buckling failure governs envelope',solved['status']=='fail_under_stated_model'
        and signal['valid_for_comparison'] and signal['bottleneck_margin'] is not None and signal['bottleneck_margin']<1
        and signal['utilizations'].get('compression/elastic_buckling')==assessment.get('buckling',{}).get('reference_utilization'),
        status=solved['status'],utilizations=signal['utilizations'],margin=signal['bottleneck_margin'])
    fixture=root/'examples/integration';c=load_case(fixture/'simplecad-beam-step.case.json')
    manifest=json.loads((fixture/'simplecad-beam.interfaces.json').read_text(encoding='utf-8'))
    mp=out/'mutable.interfaces.json';write_json(mp,manifest);c['model']['interface_manifest']=str(mp)
    path=out/'mutable.case.json';write_json(path,c)
    def changed(case,h,directory):
        mesh=make_mesh(case,h,directory)
        m=copy.deepcopy(manifest);m['regions']['mount'],m['regions']['payload']=m['regions']['payload'],m['regions']['mount']
        write_json(mp,m)
        return mesh
    solved=analyze(path,out/'mutable-interface',preview=False,mesh_factory=changed)
    check('F2 changed semantic source invalidates real mesh',solved['status']=='invalid'
        and 'source changed' in solved.get('error','') and 'assessment' not in solved
        and solved['evaluation_signal']['bottleneck_margin'] is None,status=solved['status'],error=solved.get('error'))
    robots=root/'examples/robots';case=load_robot_case(robots/'one-link.robot.json')
    case['components']=[];case['required_components']=[];case['poses']=case['poses'][:1]
    source=(robots/'one-link.urdf').read_text(encoding='utf-8').replace('assets/cadgen-beam.stl',str(robots/'assets/cadgen-beam.stl').replace('\\','/'))
    paths=[]
    for rating in (8,80):
        urdf=out/f'rating-{rating}.urdf';urdf.write_text(source.replace('effort="8"',f'effort="{rating}"'),encoding='utf-8')
        c=copy.deepcopy(case);c['model']['path']=str(urdf);path=out/f'rating-{rating}.robot.json';write_json(path,c)
        solved=analyze_robot(path,out/f'rating-{rating}',preview=True)
        check(f'F3 rating {rating} real static model resolves',solved['status']=='pass_under_stated_model')
        paths.append(out/f'rating-{rating}/result.json')
    compared=compare_results(paths);write_json(out/'ratings-comparison.json',compared)
    check('F3 changed rating is refused for fixed-actuator task',not compared['comparable'],reasons=compared['withheld_reasons'])
    verification=args.verification.resolve()
    mobile=json.loads((verification/'integration/robot-mobile/result.json').read_text(encoding='utf-8'))
    actual=design_signal(mobile)['metrics']['max_actuator_utilization']
    expected=max(e['utilization'] for p in mobile['poses'] for e in p['actuator_efforts'].values())
    check('F5 actual component FEM excludes actuator-only metric',abs(actual-expected)<1e-12,
        reported=actual,actuator_only_expected=expected)
    preloaded=json.loads((verification/'extended/preloaded-column/result.json').read_text(encoding='utf-8'))
    limit=preloaded['assessment']['conditional_body_limit']
    fixed=[l for l in limit['scaled_loads_n'] if not l['scalable']]
    html=(verification/'extended/preloaded-column/report.html').read_text(encoding='utf-8')
    check('F7 real preloaded limit keeps fixed force and reports correct semantics',fixed[0]['total_force_n']==[-20.,0,0]
        and '固定载荷和已建模自重保持不变' in html and '各组载荷同时乘以' not in html,
        factor=limit['load_pattern_scale_factor'],fixed_loads=fixed)
    contracts=0
    for filename,kind in [('result.json','result'),('signal.json','signal'),('ratings-comparison.json','comparison')]:
        for path in out.rglob(filename):
            check_contract(json.loads(path.read_text(encoding='utf-8-sig')),kind);contracts+=1
    record={'passed':all(c['passed'] for c in checks),'toolkit_version':__version__,'checks':checks,
        'output_contract_checks':contracts,'guard_tests':'tests/test_review_regressions.py additionally covers missing/nonconverged buckling, effective overrides, stale packaging, sources and report tables',
        'evidence_kind':'Real numerical/software regression of audit scenarios, not physical hardware validation',
        'known_scope':'All seven findings are tracked in the final repair record; F4 has actual packaging probes and F6 has skill/reference review in addition to these numerical checks.'}
    write_json(out/'validation.json',record)
    return 0 if record['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
