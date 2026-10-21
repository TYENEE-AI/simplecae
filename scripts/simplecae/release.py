"""Bind final package qualification to the exact delivered files and version."""
from pathlib import Path
import json
from .case import sha256


def delivery_files(root, include_validation=True, include_audit=True):
    root=Path(root)
    files=[root/name for name in ('SKILL.md','pyproject.toml','requirements-lock.txt','.gitignore')]
    files.extend(root/name for name in ('README.md','README.zh-CN.md','CHANGELOG.md','CONTRIBUTING.md','LICENSE','NOTICE.md','打开Viewer.cmd','setup.py','MANIFEST.in') if (root/name).is_file())
    folders=['agents','assets','examples','references','scripts','tests','licenses']
    if include_validation:folders.append('validation')
    for folder in folders:
        files.extend(p for p in (root/folder).rglob('*') if p.is_file()
                     and not any(x=='__pycache__' or x.endswith('.egg-info') for x in p.parts))
    if not include_audit:files=[p for p in files if p!=root/'validation/release-audit.json']
    return sorted(set(files))


def delivery_hashes(root, **options):
    return {p.relative_to(root).as_posix():sha256(p) for p in delivery_files(root,**options)}


def check_development_snapshot(root, version):
    """Reject stale development records without claiming release qualification."""
    root=Path(root)
    record=json.loads((root/'validation/development-validation.json').read_text(encoding='utf-8-sig'))
    if record.get('passed') is not True:
        raise ValueError('recorded development validation did not pass')
    if record.get('toolkit_version')!=version:
        raise ValueError('development validation version differs from current project version')
    if record.get('source_files_sha256')!=delivery_hashes(root,include_validation=False):
        raise ValueError('development validation source snapshot is stale; rerun validation before packaging')
    return record


def check_qualification(root, version):
    root=Path(root)
    audit_path=root/'validation/release-audit.json'
    if (root/'validation/public-release.json').is_file() or (
            not audit_path.is_file() and (root/'validation/public-preview.json').is_file()):
        from .public_preview import check_public_qualification
        return check_public_qualification(root,version)
    if 'dev' in version or not audit_path.is_file():raise ValueError('final release qualification is incomplete')
    audit=json.loads(audit_path.read_text(encoding='utf-8-sig'))
    if audit.get('toolkit_version')!=version:raise ValueError('qualification version differs from current project version')
    if not audit.get('complete') or set(audit.get('requirements',{}))!={f'R{i}' for i in range(14)} or any(r.get('status')!='verified' for r in audit['requirements'].values()):
        raise ValueError('all R0..R13 scoped release requirements need verified evidence')
    if tuple(int(v) for v in version.split('.')[:2])>=(1,2):
        iteration=audit.get('iteration_requirements',{})
        if set(iteration)!={f'R{i}' for i in range(1,13)} or any(r.get('status')!='verified' for r in iteration.values()):
            raise ValueError('all1.2 iteration requirements need verified, scoped evidence')
    if tuple(int(v) for v in version.split('.')[:2])>=(1,3):
        maker=audit.get('maker_requirements',{})
        if set(maker)!={f'F{i:02d}' for i in range(1,9)} or any(r.get('status')!='verified' for r in maker.values()):
            raise ValueError('all1.3 maker-feedback requirements need verified, scoped evidence')
    if tuple(int(v) for v in version.split('.'))>=(1,3,1):
        reviewed=audit.get('audit_1_3_requirements',{})
        if set(reviewed)!={f'A{i:02d}' for i in range(1,8)} or any(r.get('status')!='verified' for r in reviewed.values()):
            raise ValueError('all1.3 audit corrections need current scoped evidence')
    if tuple(int(v) for v in version.split('.')[:2])>=(1,4):
        mechanics=audit.get('mechanics_1_4_requirements',{})
        if set(mechanics)!={f'M{i:02d}' for i in range(1,6)} or any(r.get('status')!='verified' for r in mechanics.values()):
            raise ValueError('all1.4 scoped mechanics requirements need current numerical evidence')
    if tuple(int(v) for v in version.split('.')[:2])>=(1,5):
        joints=audit.get('joints_1_5_requirements',{})
        if set(joints)!={f'J{i:02d}' for i in range(1,4)} or any(r.get('status')!='verified' for r in joints.values()):
            raise ValueError('all1.5 scoped bolt/friction requirements need current numerical evidence')
    current=delivery_hashes(root,include_audit=False)
    if current!=audit.get('release_files_sha256'):
        raise ValueError('delivered source, templates, documentation or evidence differs from qualified snapshot; rerun qualification')
    verification=json.loads((root/'validation/release-verification.json').read_text(encoding='utf-8-sig'))
    if not verification.get('passed') or verification.get('toolkit_version')!=version:
        raise ValueError('full numerical verification does not qualify the current version')
    if tuple(int(v) for v in version.split('.')[:2])>=(1,4) and not verification.get('suites',{}).get('mechanics',{}).get('passed'):
        raise ValueError('1.4 mechanics native suite must pass')
    if tuple(int(v) for v in version.split('.')[:2])>=(1,5) and not verification.get('suites',{}).get('bolt-friction',{}).get('passed'):
        raise ValueError('1.5 bolt/friction native suite must pass')
    if tuple(int(v) for v in version.split('.')[:2])>=(1,6):
        from .release_checks import REQUIRED_TEST_MODULES
        current=verification.get('suites',{}).get('current-physics-and-workflow',{})
        coverage=current.get('required_module_coverage',{})
        if current.get('passed') is not True or set(coverage)!=set(REQUIRED_TEST_MODULES) or any(
                r.get('passed') is not True or r.get('tests',0)<=0
                or r.get('failed')!=0 or r.get('skipped')!=0 for r in coverage.values()):
            raise ValueError('1.6 requires complete current physics and Agent workflow regression coverage')
    if verification.get('source_files_sha256')!=delivery_hashes(root,include_validation=False):
        raise ValueError('full numerical verification belongs to different delivered sources')
    standard=json.loads((root/'validation/standard-validation.json').read_text(encoding='utf-8-sig'))
    if not standard.get('passed'):raise ValueError('recorded standard validation did not pass')
    return audit
