from __future__ import annotations
import argparse
import importlib.metadata
import json
import math
from pathlib import Path
import sys

from .case import sha256
from .solver import find_ccx


def bounded_timeout(value):
    return 'auto' if value=='auto' else float(value)


def main(argv=None):
    # Pipe encoding on Windows can differ from the console; emit machine JSON
    # and progress consistently even for Chinese/emoji paths and identifiers.
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'):stream.reconfigure(encoding='utf-8')
    p = argparse.ArgumentParser(description="SimpleCAE: use-driven engineering checks and CAD/robot iteration")
    from . import __version__
    p.add_argument('--version',action='version',version=__version__)
    sub = p.add_subparsers(dest="command", required=True)
    plan = sub.add_parser('plan', help='Review an Agent-authored use scenario and targeted check plan; never starts a solver')
    plan.add_argument('file', type=Path)
    plan.add_argument('--out', type=Path, required=True)
    task = sub.add_parser('task', help='One task file, revision-bound completion records and existing Viewer')
    task_ops = task.add_subparsers(dest='task_operation', required=True)
    task_start = task_ops.add_parser('start', help='Generate plan/cases/context from one task file; no solve unless --run is selected')
    task_start.add_argument('file', type=Path)
    task_start.add_argument('--out', type=Path, required=True)
    task_start.add_argument('--viewer-session', type=Path)
    task_start.add_argument('--run', help='Explicit immediate FEM or supported calculation check id')
    task_run = task_ops.add_parser('run', help='Run one declared immediate FEM or supported calculation check')
    task_run.add_argument('session', type=Path)
    task_run.add_argument('--check', required=True)
    task_run.add_argument('--retry-reason', help='Explicit reason for rerunning an unchanged computed check after an identified repair')
    for entry in (task_start, task_run):
        entry.add_argument('--budget-seconds', type=float, default=600)
        entry.add_argument('--timeout', type=bounded_timeout, default='auto',help='auto shares the explicit total budget; a number sets an additional per-solve cutoff')
        entry.add_argument('--ccx')
        entry.add_argument('--depth', choices=('design', 'detailed'), default='design')
        entry.add_argument('--label')
        entry.add_argument('--storage', choices=('compact', 'full'), default='compact')
    task_record = task_ops.add_parser('record', help='Record external geometry/calculation/information/test evidence, never a FEM override')
    task_record.add_argument('session', type=Path)
    task_record.add_argument('--check', required=True)
    record_source=task_record.add_mutually_exclusive_group(required=True)
    record_source.add_argument('--evidence', type=Path, help='Existing complete evidence JSON')
    record_source.add_argument('--artifact', type=Path, action='append', help='Actual external result artifact; metadata binds to this unchanged workspace')
    task_record.add_argument('--outcome', choices=('pass','fail','insufficient_evidence'))
    task_record.add_argument('--observation', action='append', help='Measured fact and acceptance comparison; repeat as needed')
    task_record.add_argument('--limitation', action='append')
    task_record.add_argument('--summary')
    task_record.add_argument('--revision',help='Expected revision_sha256 for direct artifact recording; stale/missing values are rejected')
    task_status = task_ops.add_parser('status', help='Recheck evidence hashes and summarize all check types')
    task_status.add_argument('session', type=Path)
    for entry in (task_start,task_run,task_record,task_status):
        entry.add_argument('--brief',action='store_true',help='Small Agent summary with actions; full history and fields remain on disk')
    doctor = sub.add_parser("doctor", help="Check runtime and CalculiX availability")
    doctor.add_argument("--ccx")
    tune = sub.add_parser("calibrate", help="Measure serial/parallel same-deck field parity; never grants engineering acceptance")
    tune.add_argument("input", type=Path, help="Existing self-contained static job.inp")
    tune.add_argument("--out", type=Path, required=True)
    tune.add_argument("--ccx")
    tune.add_argument("--threads", type=int, nargs="+", help="Measured candidate counts, including 1; default 1/2/4 within CPU affinity")
    tune.add_argument("--timeout", type=float, default=300)
    tune.add_argument("--profile", type=Path, help="Explicit destination for future auto selection; default only retains OUT/profile.json")
    quick=sub.add_parser('quickstart',help='Run a real STEP example; all includes pass, failure, insufficient evidence and a geometry iteration')
    quick.add_argument('--out',type=Path,required=True)
    quick.add_argument('--example',choices=('pass','fail','indeterminate','iteration','all'),default='pass')
    quick.add_argument('--ccx');quick.add_argument('--timeout',type=float,default=300)
    quick.add_argument('--quiet',action='store_true')
    quick.add_argument('--storage',choices=('compact','full'),default='compact',help='Losslessly compress native intermediates after analysis; full keeps uncompressed debug/reuse files')
    ins = sub.add_parser("inspect", help="Inspect STEP dimensions, volume and full-face inventory")
    ins.add_argument("step", type=Path)
    ins.add_argument("--out", type=Path, required=True,help='Output JSON file path, not a directory')
    ins.add_argument("--units", choices=("mm","m","cm"))
    ins.add_argument("--scene-node")
    ins.add_argument("--source-up-axis", choices=("y","z"))
    ins.add_argument('--all-bodies',action='store_true')
    ins.add_argument('--solid-id',type=int)
    ins.add_argument('--analytic-axes',action='store_true',help='Include native STEP cylinder axes/radii without centroid guessing')
    run = sub.add_parser("analyze", help="Solve >=3 meshes and issue conditional body-only assessment")
    run.add_argument("case", type=Path)
    run.add_argument("--out", type=Path, required=True)
    run.add_argument("--ccx")
    run.add_argument("--timeout", type=float, default=300)
    run.add_argument("--no-preview", action="store_true")
    run.add_argument('--storage',choices=('compact','full'),default='compact',help='Keep all fields/evidence; gzip native DAT/FRD/MSH after completion. Use full for debug/reuse')
    run.add_argument('--quiet',action='store_true',help='Suppress stage progress; final JSON remains on stdout')
    run.add_argument('--cache',type=Path,help='Reuse complete valid evidence in this cache directory (opt-in)')
    run.add_argument('--reuse-levels',type=Path,help='Reuse independently checked solved mesh levels, even from indeterminate runs; new output remains fresh')
    run.add_argument('--no-capacity',action='store_true',help='Check full requested loads without optional fixed-load decomposition/capacity extrapolation; contact preload/lock remain')
    run.add_argument('--viewer-session',type=Path,help='Record actual stages and completed evidence into an existing local Viewer session')
    run.add_argument('--label',help='Viewer revision label')
    run.add_argument('--change-note',default='',help='Concrete change and reason for this revision')
    design=sub.add_parser('design-check',help='Default bounded linear design check; opt in to detailed physics without rewriting the supplied model')
    design.add_argument('case',type=Path)
    design.add_argument('--context',type=Path,required=True,help='Decision question, model scope, assumptions and unassessed scope JSON')
    design.add_argument('--out',type=Path,required=True)
    design.add_argument('--depth',choices=('design','detailed'),default='design')
    design.add_argument('--budget-seconds',type=float,default=600,help='Total worker wall-clock budget including meshing and all solver stages')
    design.add_argument('--timeout',type=bounded_timeout,default='auto',help='auto shares the total budget; a number adds a per-native-solve cutoff')
    design.add_argument('--ccx');design.add_argument('--no-preview',action='store_true')
    design.add_argument('--viewer-session',type=Path);design.add_argument('--label')
    design.add_argument('--change-note',default='')
    design.add_argument('--predict-capacity',action='store_true',help='Opt in to conditional capacity prediction and any extra linear fixed-load solves; no product rating')
    design.add_argument('--storage',choices=('compact','full'),default='compact')
    design.add_argument('--plan', type=Path, help='Bind this solve to one immediate FEM check in a usage plan')
    design.add_argument('--check-id', help='Selected usage-plan check id; never runs all planned checks')
    design_compare=sub.add_parser('design-compare',help='Compare completed checks only with the same declared scope, assumptions and numerical task')
    design_compare.add_argument('reviews',type=Path,nargs='+');design_compare.add_argument('--out',type=Path,required=True)
    view=sub.add_parser('view',help='Create or reopen a local evidence Viewer; no browser-triggered solver execution')
    view.add_argument('results',type=Path,nargs='*')
    destination=view.add_mutually_exclusive_group(required=True)
    destination.add_argument('--out',type=Path,help='Create a fresh review session')
    destination.add_argument('--session',type=Path,help='Reopen an existing review session; supplied results are added as revisions')
    view.add_argument('--title',default='SimpleCAE · 分析审阅')
    view.add_argument('--serve',action='store_true',help='Serve only this Viewer on 127.0.0.1; enables stage updates and saved annotations')
    view.add_argument('--open',action='store_true',help='Open the local Viewer in the default browser (requires --serve)')
    view.add_argument('--port',type=int,default=0)
    batch=sub.add_parser('campaign',help='Run a typed case list with native-crash isolation and source-bound resume receipts')
    batch.add_argument('manifest',type=Path);batch.add_argument('--out',type=Path,required=True)
    batch.add_argument('--ccx');batch.add_argument('--timeout',type=float,default=300)
    batch.add_argument('--no-preview',action='store_true');batch.add_argument('--resume',action='store_true')
    batch.add_argument('--quiet',action='store_true');batch.add_argument('--reuse-levels',type=Path)
    batch.add_argument('--storage',choices=('compact','full'),default='compact')
    ex = sub.add_parser("examples", help="Generate STEP benchmark bars, a bracket and input cases in a fresh directory")
    ex.add_argument("--out", type=Path, required=True)
    bench = sub.add_parser("validate", help="Actually solve the standard analytic cases")
    bench.add_argument("--out", type=Path, required=True)
    bench.add_argument("--ccx")
    bench.add_argument("--timeout", type=float, default=300)
    bench.add_argument("--suite",choices=("standard","extended","integration","materials","assemblies","general","robots","maker","mechanics","bolt-friction","joint-compliance","planar-footprints","contact-opening","design-checks"),default="standard")
    compare=sub.add_parser('compare',help='Compare candidates only under a shared verified task contract')
    compare.add_argument('results',type=Path,nargs='+')
    compare.add_argument('--out',type=Path,required=True)
    guide=sub.add_parser('prepare',help='Inspect a model and generate a local guided input form; no solve or inferred physical facts')
    guide.add_argument('model',type=Path)
    guide.add_argument('--out',type=Path,required=True)
    guide.add_argument('--units',choices=('m','mm','cm'))
    guide.add_argument('--scene-node')
    guide.add_argument('--source-up-axis',choices=('y','z'))
    grip=sub.add_parser('gripper-task',help='Compile explicit two-finger application facts into a robot load case')
    grip.add_argument('task',type=Path)
    grip.add_argument('--out',type=Path,required=True)
    task_run=sub.add_parser('analyze-gripper',help='Compile and analyze all required grip-force endpoints, with per-endpoint preview and coverage report')
    task_run.add_argument('task',type=Path);task_run.add_argument('--out',type=Path,required=True)
    task_run.add_argument('--ccx');task_run.add_argument('--timeout',type=float,default=300)
    task_run.add_argument('--no-preview',action='store_true');task_run.add_argument('--quiet',action='store_true')
    task_run.add_argument('--cache',type=Path);task_run.add_argument('--reuse-levels',type=Path)
    task_run.add_argument('--include-nominal',action='store_true');task_run.add_argument('--ledger',type=Path)
    task_run.add_argument('--storage',choices=('compact','full'),default='compact')
    preview=sub.add_parser('preview',help='Show support components and declared equivalent wrenches before solving')
    preview.add_argument('case',type=Path)
    preview.add_argument('--out',type=Path,required=True)
    summary=sub.add_parser('summarize',help='Combine analysis findings and uncovered scope into an application report')
    summary.add_argument('results',type=Path,nargs='+')
    summary.add_argument('--out',type=Path,required=True)
    summary.add_argument('--title',default='SimpleCAE 方案评估')
    summary.add_argument('--ledger',type=Path,help='Attach a source-bound product evidence ledger; never grants certification')
    evidence=sub.add_parser('evidence',help='Create or review a file-bound product evidence checklist')
    evidence.add_argument('files',type=Path,nargs='+')
    evidence.add_argument('--out',type=Path,required=True)
    evidence.add_argument('--init',action='store_true',help='Create an editable ledger JSON from source file bindings')
    evidence.add_argument('--title',default='产品证据清单')
    interface=sub.add_parser('interface-check',help='Compare STEP dimensions and analytic cylinder axes against an explicit source-bound interface')
    interface.add_argument('file',type=Path)
    interface.add_argument('--out',type=Path,required=True)
    contract=sub.add_parser('check',help='Validate JSON syntax and case semantics without invoking the solver')
    contract.add_argument('file',type=Path)
    contract.add_argument('--kind',choices=('case','result','signal','comparison','evidence','evidence-review','interface','task-family','gripper-task','campaign'),default='case')
    args = p.parse_args(argv)
    recorder = None
    try:
        if hasattr(args, "timeout") and args.timeout!='auto' and (not math.isfinite(args.timeout) or args.timeout <= 0 or args.timeout > 86400):
            raise ValueError("timeout must be positive and <= 86400 seconds")
        if args.command == 'task':
            from .task import start_task, run_task_check, record_task_check, task_status, brief_task_status
            if args.task_operation == 'start':
                output = start_task(args.file, args.out, viewer_session=args.viewer_session)
                if args.run:
                    output = run_task_check(args.out, args.run, budget_seconds=args.budget_seconds,
                        timeout=args.timeout, ccx=args.ccx, depth=args.depth, label=args.label, storage=args.storage)
            elif args.task_operation == 'run':
                output = run_task_check(args.session, args.check, budget_seconds=args.budget_seconds,
                    timeout=args.timeout, ccx=args.ccx, depth=args.depth, label=args.label, storage=args.storage,
                    retry_reason=args.retry_reason)
            elif args.task_operation == 'record':
                output = record_task_check(args.session, args.check, args.evidence,
                    artifacts=args.artifact,outcome=args.outcome,observations=args.observation,
                    limitations=args.limitation,summary=args.summary,revision_sha256=args.revision)
            else:
                output = task_status(args.session)
            if args.brief:
                output=brief_task_status(output)
        elif args.command == 'plan':
            from .use_plan import prepare_plan
            r = prepare_plan(args.file, args.out)
            output = {k: r[k] for k in ('recommendation', 'next_checks', 'fem_checks', 'calculation_checks', 'worker_started', 'whole_product_pass_available')}
            output['report'] = str(args.out.resolve() / 'plan-review.html')
        elif args.command == "doctor":
            from .execution import hardware_snapshot
            exe = find_ccx(args.ccx)
            output = {"status": "ready", "python": sys.executable, "ccx": str(exe), "ccx_sha256": sha256(exe),
                      "hardware":hardware_snapshot(),
                      "packages": {n: importlib.metadata.version(n) for n in ("gmsh", "numpy", "matplotlib")}}
        elif args.command == "calibrate":
            from .parallel import calibrate
            report = calibrate(args.input, args.out, args.ccx, args.threads, args.timeout, args.profile)
            output = {"profile": str(args.out.resolve() / "profile.json"),
                      "passed": report["passed"],
                      "samples": report["samples"],
                      "meaning": report["meaning"]}
        elif args.command=='design-check':
            from .design_check import design_check
            review=design_check(args.case,args.out,context_path=args.context,depth=args.depth,
                budget_seconds=args.budget_seconds,timeout=args.timeout,ccx=args.ccx,preview=not args.no_preview,
                viewer_session=args.viewer_session,label=args.label,change_note=args.change_note,predict_capacity=args.predict_capacity,storage=args.storage,
                plan_path=args.plan,check_id=args.check_id)
            output={'execution':review['execution']['state'],'model_status':review['feedback']['model_status'],
                    'review':str(args.out.resolve()/'design-review.json'),'report':str(args.out.resolve()/'design-review.html'),
                    'whole_product_pass_available':False}
        elif args.command=='design-compare':
            from .design_check import compare_design_checks
            from .case import write_json
            output=compare_design_checks(args.reviews);write_json(args.out,output)
        elif args.command=='view':
            from .workbench import create_session, session_config, add_result, export_session, serve
            if not 0 <= args.port <= 65535:raise ValueError('Viewer port must be 0–65535')
            if args.open and not args.serve:raise ValueError('--open requires --serve')
            session=args.out.resolve() if args.out else args.session.resolve()
            if args.out:create_session(session,args.title)
            else:session_config(session)
            for result in args.results:add_result(session,result)
            export_session(session)
            if args.serve:serve(session,args.port,args.open)
            output={'viewer':str(session/'index.html'),'session':str(session),'meaning':'Local evidence review, not product acceptance or a new solve.'}
        elif args.command=='quickstart':
            from .quickstart import run_quickstart
            from .progress import cli_progress
            r=run_quickstart(args.out,args.example,args.ccx,args.timeout,None if args.quiet else cli_progress)
            output={'passed':r['passed'],'meaning':r['meaning'],'summary':str(args.out.resolve()/'quickstart.json'),'reports':r['reports']}
        elif args.command == "inspect":
            from .geometry import inspect
            model={'path':str(args.step.resolve())}
            for field in ('units','scene_node','source_up_axis'):
                if getattr(args,field) is not None: model[field]=getattr(args,field)
            if args.solid_id is not None:model['solid_id']={'id':args.solid_id,'geometry_sha256':sha256(args.step.resolve())}
            if args.all_bodies:
                if args.analytic_axes:raise ValueError('inspect one selected STEP solid for analytic axes; use --solid-id after body inventory')
                from .geometry import inspect_bodies
                output=inspect_bodies(args.step.resolve(),args.out.resolve(),model)
            else:output = inspect(args.step.resolve(), args.out.resolve(),model,analytic_axes=args.analytic_axes)
        elif args.command == "examples":
            from .benchmarks import generate_examples
            output = {"examples": str(generate_examples(args.out.resolve()))}
        elif args.command == "validate":
            if args.suite=='design-checks':
                from .design_validation import validate_design_checks
                report=validate_design_checks(args.out,args.ccx,args.timeout)
            elif args.suite=='contact-opening':
                from .opening_validation import validate_contact_opening
                report=validate_contact_opening(args.out,args.ccx,args.timeout)
            elif args.suite=='planar-footprints':
                from .footprint_validation import validate_footprints
                report=validate_footprints(args.out,args.ccx,args.timeout)
            elif args.suite=='joint-compliance':
                from .joint_validation import validate_joint_compliance
                report=validate_joint_compliance(args.out.resolve(),args.ccx,args.timeout)
            elif args.suite=='bolt-friction':
                from .bolt_friction_validation import validate_bolt_friction
                report=validate_bolt_friction(args.out.resolve(),args.ccx,args.timeout)
            elif args.suite=='mechanics':
                from .mechanics_validation import validate_mechanics
                report=validate_mechanics(args.out.resolve(),args.ccx,args.timeout)
            elif args.suite=='maker':
                from .maker_validation import validate_maker
                report=validate_maker(args.out.resolve(),args.ccx,args.timeout)
            elif args.suite=='robots':
                from .robot_validation import validate_robots
                report=validate_robots(args.out.resolve(),args.ccx,args.timeout)
            elif args.suite=='general':
                from .general_validation import validate_general
                report=validate_general(args.out.resolve(),args.ccx,args.timeout)
            elif args.suite=='assemblies':
                from .assembly_validation import validate_assemblies
                report=validate_assemblies(args.out.resolve(),args.ccx,args.timeout)
            elif args.suite=='materials':
                from .material_validation import validate_materials
                report=validate_materials(args.out.resolve(),args.ccx,args.timeout)
            elif args.suite=='integration':
                from .integration_validation import validate_integration
                report=validate_integration(args.out.resolve(),args.ccx,args.timeout)
            elif args.suite=="extended":
                from .extended_validation import validate_extended
                report=validate_extended(args.out.resolve(),args.ccx,args.timeout)
            else:
                from .benchmarks import validate_benchmarks
                report = validate_benchmarks(args.out.resolve(), args.ccx, args.timeout)
            output = {"passed": report["passed"], "validation": str(args.out.resolve() / "validation.json")}
        elif args.command=='campaign':
            from .campaign import run_campaign
            report=run_campaign(args.manifest,args.out,ccx=args.ccx,timeout=args.timeout,preview=not args.no_preview,resume=args.resume,reuse_levels=args.reuse_levels,storage=args.storage)
            output={'campaign':str(args.out.resolve()/'campaign-result.json'),**{k:report[k] for k in ('status','status_counts','all_results_valid','completed_count','requested_count')}}
        elif args.command=='compare':
            from .signals import compare_results
            from .case import write_json
            comparison=compare_results(args.results);write_json(args.out,comparison)
            output={'comparable':comparison['comparable'],'comparison':str(args.out.resolve()),'withheld_reasons':comparison['withheld_reasons']}
        elif args.command=='prepare':
            from .product import prepare
            output=prepare(args.model,args.out,{k:getattr(args,k) for k in ('units','scene_node','source_up_axis') if getattr(args,k) is not None})
        elif args.command=='check':
            from .api import check_case
            from .schemas import check_contract
            if args.kind=='case':check_case(args.file)
            elif args.kind=='campaign':
                from .campaign import load_campaign
                load_campaign(args.file)
            elif args.kind=='gripper-task':
                from .api import check_gripper_task
                check_gripper_task(args.file)
            elif args.kind=='evidence':
                from .evidence import inspect_ledger
                inspect_ledger(args.file)
            elif args.kind=='interface':
                from .interface_check import load_interface_case
                load_interface_case(args.file)
            else:check_contract(json.loads(args.file.read_text(encoding='utf-8-sig')),args.kind)
            output={'status':'contract_valid','kind':args.kind,'file':str(args.file.resolve()),'meaning':'Syntax/input checks only, not numerical or physical validation'}
        elif args.command=='gripper-task':
            from .grasp import compile_gripper_task
            from .case import write_json
            from .api import check_gripper_task
            task=check_gripper_task(args.task)
            if 'force_measurement' in task:
                from .force_envelope import compile_force_envelope
                output=compile_force_envelope(task,args.task,args.out)
            else:
                case=compile_gripper_task(task,args.task)
                args.out.mkdir(parents=True,exist_ok=False)
                write_json(args.out/'gripper.robot.json',case)
                from .api import check_case
                check_case(args.out/'gripper.robot.json')
                output={'case':str((args.out/'gripper.robot.json').resolve()),'meaning':'Declared grip application/load generation; run analyze for poses, actuator, friction and requested component criteria. Unknown physical conditions remain false.'}
        elif args.command=='preview':
            from .preflight import preview_case
            output=preview_case(args.case,args.out)
        elif args.command=='analyze-gripper':
            from .task_family import analyze_gripper_task
            from .progress import cli_progress
            r=analyze_gripper_task(args.task,args.out,ccx=args.ccx,timeout=args.timeout,preview=not args.no_preview,
                                   progress=None if args.quiet else cli_progress,cache=args.cache,reuse_levels=args.reuse_levels,
                                   include_nominal=args.include_nominal,ledger=args.ledger,storage=args.storage)
            output={'status':r['status'],'result':str(args.out.resolve()/'task-family.json'),'report':str(args.out.resolve()/'task-family.html')}
            if r.get('error'):output['error']=r['error']
        elif args.command=='summarize':
            from .application import summarize_application
            output=summarize_application(args.results,args.out,args.title,ledger=args.ledger)
        elif args.command=='evidence':
            from .evidence import init_ledger,review_ledger
            if args.init:output=init_ledger(args.files,args.out,args.title)
            else:
                if len(args.files)!=1:raise ValueError('review one evidence ledger at a time')
                output=review_ledger(args.files[0],args.out)
        elif args.command=='interface-check':
            from .interface_check import measure_interface
            output=measure_interface(args.file,args.out)
        else:
            from .progress import cli_progress
            callback=None if args.quiet else cli_progress
            if args.viewer_session:
                from .workbench import RunRecorder
                recorder=RunRecorder(args.viewer_session,args.case,args.out,args.label,args.change_note,callback)
                callback=recorder
            options={'progress':callback,'cache':args.cache,'reuse_levels':args.reuse_levels,'predict_capacity':not args.no_capacity}
            header=json.loads(args.case.read_text(encoding='utf-8-sig'))
            if header.get('schema_version') in ('fatigue-data-1.0', 'creep-data-1.0'):
                if args.cache or args.reuse_levels:
                    raise ValueError('Durability data checks do not use solver caches')
                from .durability import analyze as analyze_durability
                report=analyze_durability(args.case,args.out,progress=callback)
            elif header.get('schema_version')=='motion-loads-1.0':
                if args.cache or args.reuse_levels:
                    raise ValueError('Motion load cache/reuse is unsupported')
                from .motion import analyze as analyze_motion
                report=analyze_motion(args.case,args.out,progress=callback)
            elif header.get('schema_version')=='modal-solid-1.0':
                if args.cache or args.reuse_levels:
                    raise ValueError('Modal cache/reuse is unsupported')
                from .modal import analyze as analyze_modal
                report=analyze_modal(args.case,args.out,args.ccx,args.timeout,progress=callback)
            elif header.get('schema_version')=='thermal-solid-1.0':
                if args.cache or args.reuse_levels:
                    raise ValueError('Solid thermal cache/reuse is unsupported')
                from .thermal_solid import analyze as analyze_thermal
                report=analyze_thermal(args.case,args.out,args.ccx,args.timeout)
            elif header.get('schema_version')=='thermal-network-1.0':
                if args.cache or args.reuse_levels:
                    raise ValueError('Thermal network cache/reuse is unsupported')
                from .thermal_network import analyze as analyze_thermal
                report=analyze_thermal(args.case,args.out)
            elif header.get('schema_version')=='robot-1.0':
                from .robot import analyze_robot
                report=analyze_robot(args.case,args.out,args.ccx,args.timeout,not args.no_preview,**options)
            elif header.get('schema_version')=='assembly-1.0':
                from .assembly import analyze_assembly
                report=analyze_assembly(args.case,args.out,args.ccx,args.timeout,not args.no_preview,**options)
            else:
                from .workflow import analyze
                report = analyze(args.case, args.out.resolve(), args.ccx, args.timeout, not args.no_preview,**options)
            output = {"status": report["status"], "result": str(args.out.resolve() / "result.json"),
                      "report": str(args.out.resolve() / "report.html")}
            if report.get("error"):
                output["error"] = report["error"]
            if recorder:
                viewer_error=recorder.finish()
                if viewer_error:output['viewer_error']=viewer_error
        if args.command in ('analyze','quickstart','analyze-gripper'):
            from .retention import retain_output
            output['storage'] = {k:v for k,v in retain_output(args.out,args.storage).items() if k in ('mode','saved_bytes','errors')}
        print(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False))
        if args.command=='design-check' and output.get('execution') in ('budget_exhausted','needs_explicit_model'):
            return 3
        if args.command=='design-check' and output.get('execution')=='analysis_failed':
            return 2
        return 2 if output.get("status") == "invalid" or output.get("passed") is False else 1 if args.command=='campaign' and not output['all_results_valid'] else 0
    except Exception as exc:
        if recorder:recorder.fail(f'{type(exc).__name__}: {exc}')
        print(json.dumps({"status": "invalid", "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 2
    except KeyboardInterrupt:
        if recorder:recorder.fail('Interrupted by user; no completed result was registered')
        return 130
