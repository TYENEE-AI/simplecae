"""Source-only public profile: omit private history, retain exact source qualification."""
from pathlib import Path
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from .release import delivery_files,delivery_hashes

SUITES={'standard','extended','materials','assemblies','integration','general','robots','maker','mechanics','bolt-friction',
        'joint-compliance','planar-footprints','contact-opening','design-checks','current-physics-and-workflow'}
ONBOARDING_CHECKS=('fresh_virtualenv','native_tools_downloaded','agent_cli','viewer_iteration','compact_evidence')


def snapshot_digest(root):
    return hashlib.sha256(json.dumps(delivery_hashes(root,include_validation=False),sort_keys=True,separators=(',',':')).encode('utf-8')).hexdigest()


def scan_public_files(root):
    root=Path(root).resolve();files=delivery_files(root,include_validation=False)
    private_patterns=[re.compile(rb'[A-Za-z]:[\\/]+Users[\\/]+[^\\/\s\"\']+[\\/]',re.I),
                      re.compile(rb'(?:/home|/Users)/[^/\s]+/'),
                      re.compile(rb'\bgh[pousr]_[A-Za-z0-9]{30,}\b'),
                      re.compile(rb'\bAKIA[A-Z0-9]{16}\b'),
                      re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----')]
    # Match the actual checkout path in either slash convention, including JSON escaping.
    locations=[str(root),str(root.parent)]
    for loc in locations:
        for value in {loc,loc.replace('\\','/'),loc.replace('\\','\\\\')}:
            private_patterns.append(re.compile(re.escape(value.encode('utf-8')),re.I))
    for path in files:
        if path.is_symlink() or not path.resolve().is_relative_to(root):raise ValueError('public source escapes its root')
        relative=path.relative_to(root).as_posix()
        if path.suffix.lower() in {'.exe','.dll','.whl','.zip','.pyc','.npz'}:raise ValueError(f'local binary/cache in public source: {relative}')
        data=path.read_bytes()
        if any(p.search(data) for p in private_patterns):raise ValueError(f'private path or credential pattern in public source: {relative}')
    return {'passed':True,'source_files':len(files),'scope':'Allowlisted source/resources, private home/checkout paths and common credential patterns; not a guarantee against all confidential content.'}


def validate_receipt(root,version,receipt):
    channel=receipt.get('channel')
    if receipt.get('toolkit_version')!=version or channel not in ('developer-preview','release'):raise ValueError('public source version/channel mismatch')
    if channel=='release':
        if re.fullmatch(r'\d+\.\d+\.\d+',version) is None:
            raise ValueError('public release requires a final numeric version')
        validate_readiness(root,receipt.get('release_readiness',{}))
    if receipt.get('source_files_sha256')!=delivery_hashes(root,include_validation=False):raise ValueError('public preview source snapshot differs; rerun qualification')
    onboarding=receipt.get('onboarding',{})
    if onboarding.get('passed') is not True or any(onboarding.get(name) is not True for name in ONBOARDING_CHECKS):
        raise ValueError('public preview requires completed isolated installation, Agent, Viewer and compact-evidence checks')
    if onboarding.get('source_snapshot_sha256')!=snapshot_digest(root):
        raise ValueError('onboarding verification belongs to different sources')
    evidence=receipt.get('verification',{})
    suites=evidence.get('suites',{})
    if evidence.get('passed') is not True or set(suites)!=SUITES or any(s.get('passed') is not True or not isinstance(s.get('checks'),int) or s['checks']<=0 for s in suites.values()):
        raise ValueError('public preview requires all real numerical suites, including bolt-friction')
    from .release_checks import REQUIRED_TEST_MODULES
    coverage=suites['current-physics-and-workflow'].get('required_module_coverage',{})
    if set(coverage)!=set(REQUIRED_TEST_MODULES) or any(
            r.get('passed') is not True or not isinstance(r.get('tests'),int) or r['tests']<=0
            or r.get('failed')!=0 or r.get('skipped')!=0 for r in coverage.values()):
        raise ValueError('current physics and workflow test coverage is missing, failed or skipped')
    if evidence.get('numerical_checks')!=sum(s['checks'] for s in suites.values()) or evidence.get('output_contract_checks',0)<=0:
        raise ValueError('public preview numerical/contract evidence is incomplete')
    for name in ('guards','examples','licenses','privacy_scan'):
        if receipt.get(name,{}).get('passed') is not True:raise ValueError(f'public preview {name} evidence is incomplete')
    if receipt['guards'].get('tests',0)<=0 or any(receipt['guards'].get(n,0) for n in ('failures','errors','skipped')):
        raise ValueError('public preview requires completed guard tests')
    examples={c.get('example'):c for c in receipt['examples'].get('checks',[])}
    expected={'pass':'pass_under_stated_model','fail':'fail_under_stated_model','indeterminate':'indeterminate','iteration':'pass_under_stated_model'}
    if set(examples)!=set(expected)|{'same-task-iteration'} or any(examples[n].get('status')!=s or examples[n].get('passed') is not True for n,s in expected.items()) or examples['same-task-iteration'].get('passed') is not True:
        raise ValueError('public preview example coverage is incomplete')
    import importlib.util
    spec=importlib.util.spec_from_file_location('simplecae_license_audit',Path(root)/'scripts/audit_dependencies.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    if module.check(Path(root))!=receipt['licenses']:raise ValueError('public dependency license evidence differs')
    scan_public_files(root)
    return receipt


def validate_readiness(root,record):
    """Current launch contract, separate from unchanged numerical acceptance."""
    if record.get('source_snapshot_sha256')!=snapshot_digest(root):
        raise ValueError('release readiness belongs to different sources')
    if record.get('passed') is not True or record.get('open_release_blockers')!=[]:
        raise ValueError('release readiness has unresolved release blockers')
    required={'agent_workflow','calculation_display','resources','exceptions_gates',
              'product_review','documentation_licenses'}
    areas=record.get('areas',{})
    if set(areas)!=required or any(v.get('passed') is not True or not v.get('evidence')
                                  for v in areas.values()):
        raise ValueError('release readiness must cover all current audit areas')
    platforms=record.get('platforms',{})
    checks=('fresh_install','cli','worker','viewer_iteration','compact_storage','regression')
    if set(platforms)!={'Windows','Ubuntu'} or any(
            p.get('passed') is not True or not p.get('environment')
            or not p.get('evidence') or any(p.get(k) is not True for k in checks)
            for p in platforms.values()):
        raise ValueError('release needs actual Windows and Ubuntu installation/workflow evidence')
    hosts=record.get('agents',{})
    if set(hosts)!={'codex','claude','deepseek','omp','pi'} or any(
            h.get('discovery_install_checked') is not True
            or h.get('portable_cli_checked') is not True
            or not isinstance(h.get('live_agent_session_tested'),bool)
            or not h.get('evidence') for h in hosts.values()):
        raise ValueError('release needs five-host integration evidence with explicit live-session scope')
    examples=record.get('showcases',{})
    if set(examples)!={'thermal_bridge','inspection_arm','sensor_mast'} or any(
            e.get('workflow_verified') is not True or not e.get('evidence')
            or e.get('whole_product_pass_available') is not False for e in examples.values()):
        raise ValueError('release needs substantive showcase execution without product-pass promotion')
    return record


def make_public_receipt(root,version,channel='developer-preview'):
    root=Path(root)
    if channel not in ('developer-preview','release'):
        raise ValueError('unknown public distribution channel')
    existing=root/'validation'/('public-release.json' if channel=='release' else 'public-preview.json')
    if not (root/'validation/release-verification.json').is_file():
        receipt=json.loads(existing.read_text(encoding='utf-8'))
        if receipt.get('channel')!=channel:raise ValueError('public distribution channel differs')
        return validate_receipt(root,version,receipt)
    raw=json.loads((root/'validation/release-verification.json').read_text(encoding='utf-8'))
    preview=json.loads((root/'validation/preview-verification.json').read_text(encoding='utf-8'))
    if raw.get('toolkit_version')!=version or raw.get('source_files_sha256')!=delivery_hashes(root,include_validation=False):
        raise ValueError('numerical verification belongs to different version or sources')
    if preview.get('source_files_sha256')!=delivery_hashes(root,include_validation=False):raise ValueError('preview verification belongs to different sources')
    onboarding=json.loads((root/'validation/onboarding-verification.json').read_text(encoding='utf-8'))
    tree=ET.parse(root/'validation/guard-tests.xml')
    guards={k:sum(int(s.get(k,0)) for s in tree.getroot().iter('testsuite')) for k in ('tests','failures','errors','skipped')}
    guards['passed']=guards['tests']>0 and not any(guards[k] for k in ('failures','errors','skipped'))
    receipt={'schema_version':'public-preview-2','toolkit_version':version,'channel':'developer-preview',
             'complete':True,'recorded_at_utc':raw['recorded_at_utc'],
             'source_files_sha256':delivery_hashes(root,include_validation=False),
             'verification':{k:raw[k] for k in ('passed','platform','python','numerical_checks','output_contract_checks','runtime_versions')},
             'guards':guards,'examples':preview['examples'],'licenses':preview['licenses'],
             'privacy_scan':scan_public_files(root),
             'onboarding':{name:onboarding[name] for name in ('passed','source_snapshot_sha256','scope',*ONBOARDING_CHECKS)},
             'scope':'Windows numerical/software verification, not independent novice, cross-platform, physical material or product qualification. Private historical audits and raw solver outputs are omitted. Regenerate with the shipped scripts.',
             'evidence_records_sha256':{n:hashlib.sha256((root/'validation'/n).read_bytes()).hexdigest() for n in ('release-verification.json','guard-tests.xml','preview-verification.json','onboarding-verification.json')}}
    receipt['verification']['suites']={name:{'passed':s['passed'],'checks':s['checks']} for name,s in raw['suites'].items()}
    receipt['verification']['suites']['current-physics-and-workflow']['required_module_coverage']=raw['suites']['current-physics-and-workflow'].get('required_module_coverage',{})
    if channel=='release':
        readiness=root/'validation/release-readiness.json'
        receipt.update(schema_version='public-release-1',channel='release',
                       release_readiness=json.loads(readiness.read_text(encoding='utf8')),
                       scope='Source-bound numerical/software verification and actual Windows/WSL Ubuntu installation/workflows. Agent discovery/CLI checks are distinguished from live host/model sessions. No physical product certification.')
        receipt['evidence_records_sha256']['release-readiness.json']=hashlib.sha256(readiness.read_bytes()).hexdigest()
    return validate_receipt(root,version,receipt)


def check_public_qualification(root,version):
    root=Path(root)
    actual={p.relative_to(root/'validation').as_posix() for p in (root/'validation').rglob('*') if p.is_file()}
    name='public-release.json' if (root/'validation/public-release.json').is_file() else 'public-preview.json'
    if actual!={name}:raise ValueError('public source contains unexpected validation history')
    receipt=json.loads((root/'validation'/name).read_text(encoding='utf-8'))
    if (name=='public-release.json')!=(receipt.get('channel')=='release'):
        raise ValueError('public receipt filename/channel mismatch')
    return validate_receipt(root,version,receipt)
