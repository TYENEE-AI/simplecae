"""Run a source notebook and export native interfaces in its CAD environment."""
import argparse
import ast
import json
import sys
from pathlib import Path
from . import export_for_cae, HandoffError


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('notebook',type=Path)
    parser.add_argument('--required',type=Path,help='JSON mapping interface.* tags to expected counts/types')
    parser.add_argument('--robot-materials',type=Path,help='Export a native robot tree; JSON mapping component IDs to sourced density_kg_m3')
    parser.add_argument('--out',default='out/cae')
    parser.add_argument('--frame',choices=['part_local','world'],default='part_local')
    parser.add_argument('--occurrence',help='Exact component-ID path to one leaf part')
    parser.add_argument('--id')
    parser.add_argument('--set',action='append',default=[],metavar='NAME=VALUE')
    parser.add_argument('--timeout',type=float,default=3000)
    args=parser.parse_args()
    try:
        if args.notebook.suffix.lower()!='.py':
            raise HandoffError('Provide the source .py notebook; rerun it instead of reading .scadpkg BREP.',code='rerun_source_notebook')
        if bool(args.required)==bool(args.robot_materials):raise HandoffError('Choose exactly one of --required (part interfaces) or --robot-materials (native robot tree)')
        if args.timeout<=0: raise HandoffError('--timeout must be positive')
        overrides={}
        for item in args.set:
            name,sep,value=item.partition('=')
            if not sep or not name: raise HandoffError('--set needs NAME=VALUE')
            try: overrides[name]=ast.literal_eval(value)
            except (ValueError,SyntaxError): overrides[name]=value
        from simplecadapi.runtime import run_notebook
        run=run_notebook(args.notebook,id=args.id,overrides=overrides,timeout=args.timeout)
        if args.robot_materials:
            from .robot import export_robot_for_cae
            report=export_robot_for_cae(run,args.out,materials=json.loads(args.robot_materials.read_text(encoding='utf-8-sig')))
        else:
            report=export_for_cae(run,args.out,required=json.loads(args.required.read_text(encoding='utf-8-sig')),
                                  frame=args.frame,occurrence=args.occurrence)
        print(json.dumps(report,ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({'status':'invalid','code':getattr(exc,'code','native_export_failed'),
                          'message':str(exc),'details':getattr(exc,'details',{})},ensure_ascii=False),file=sys.stderr)
        return 2
    return 0


if __name__=='__main__':raise SystemExit(main())
