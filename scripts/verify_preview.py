"""Reproduce onboarding examples and license/privacy checks against frozen sources."""
from pathlib import Path
import argparse
import importlib.util
from simplecae import __version__
from simplecae.case import write_json
from simplecae.quickstart import run_quickstart
from simplecae.release import delivery_hashes
from simplecae.public_preview import scan_public_files


def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--ccx');a=p.parse_args()
    out=a.out.resolve();out.mkdir(parents=True,exist_ok=False);root=Path(__file__).resolve().parents[1]
    snapshot=delivery_hashes(root,include_validation=False)
    examples=run_quickstart(out/'examples','all',a.ccx)
    spec=importlib.util.spec_from_file_location('dependency_audit',root/'scripts/audit_dependencies.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    licenses=module.check(root);privacy=scan_public_files(root)
    report={'passed':examples['passed'] and licenses['passed'] and privacy['passed'] and snapshot==delivery_hashes(root,include_validation=False),
            'toolkit_version':__version__,'source_files_sha256':snapshot,
            'examples':{k:examples[k] for k in ('passed','checks','meaning')},'licenses':licenses,'privacy_scan':privacy,
            'scope':'Native example/software and source/notice checks; no independent novice, physical product or cross-platform qualification.'}
    write_json(out/'preview-verification.json',report)
    print({'passed':report['passed'],'record':str(out/'preview-verification.json')});return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
