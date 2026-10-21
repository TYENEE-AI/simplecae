"""Privacy and qualification invariants for the source-only distribution profile."""
import copy
import importlib.util
import json
from pathlib import Path
import shutil
import pytest
from simplecae.case import write_json
from simplecae.public_preview import SUITES,ONBOARDING_CHECKS,snapshot_digest,validate_receipt,scan_public_files,check_public_qualification
from simplecae.release import delivery_files,delivery_hashes
from simplecae.signals import structural_contract
from simplecae import __version__
from simplecae.release_checks import REQUIRED_TEST_MODULES

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture
def public_source(tmp_path):
    root=tmp_path/'public'
    for source in delivery_files(ROOT,include_validation=False):
        target=root/source.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
    spec=importlib.util.spec_from_file_location('audit_dependencies',root/'scripts/audit_dependencies.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    manifest=json.loads((root/'examples/preview/examples.json').read_text(encoding='utf-8'))
    # Synthetic records exercise receipt integrity only; never count as native verification.
    receipt={'toolkit_version':__version__,'channel':'developer-preview','source_files_sha256':delivery_hashes(root,include_validation=False),
             'verification':{'passed':True,'suites':{n:{'passed':True,'checks':1} for n in SUITES},'numerical_checks':len(SUITES),'output_contract_checks':1},
             'guards':{'passed':True,'tests':1,'failures':0,'errors':0,'skipped':0},
             'onboarding':{'passed':True,'source_snapshot_sha256':snapshot_digest(root),**{name:True for name in ONBOARDING_CHECKS}},
             'licenses':module.check(root),'privacy_scan':{'passed':True},
             'examples':{'passed':True,'checks':[{'example':name,'status':spec['expected_status'],'passed':True} for name,spec in manifest.items()]+[{'example':'same-task-iteration','passed':True}]}}
    receipt['verification']['suites']['current-physics-and-workflow']['required_module_coverage']={
        name:{'passed':True,'tests':1,'failed':0,'skipped':0} for name in REQUIRED_TEST_MODULES}
    return root,receipt


def test_public_receipt_binds_complete_sources_and_rejects_private_validation(public_source):
    root,receipt=public_source
    write_json(root/'validation/public-preview.json',receipt)
    assert check_public_qualification(root,__version__)
    write_json(root/'validation/private-history.json',{'private':'example'})
    with pytest.raises(ValueError,match='unexpected validation history'):check_public_qualification(root,__version__)


@pytest.mark.parametrize('change',['README.md','validation/README.md','LICENSE','added','removed'])
def test_public_receipt_rejects_changed_or_incomplete_source_set(public_source,change):
    root,receipt=public_source
    if change=='added':(root/'scripts/extra.py').write_text('extra')
    elif change=='removed':(root/'examples/preview/beam.step').unlink()
    else:(root/change).write_text('changed')
    with pytest.raises(ValueError,match='snapshot'):validate_receipt(root,__version__,receipt)


@pytest.mark.parametrize('change',['suite','counts','skipped','indeterminate','iteration','license','onboarding','onboarding-source','physics-coverage'])
def test_public_receipt_cannot_promote_missing_or_failed_evidence(public_source,change):
    root,receipt=public_source;bad=copy.deepcopy(receipt)
    if change=='suite':bad['verification']['suites'].pop('mechanics')
    elif change=='counts':bad['verification']['numerical_checks']+=1
    elif change=='skipped':bad['guards']['skipped']=1
    elif change=='indeterminate':bad['examples']['checks'][2]['status']='pass_under_stated_model'
    elif change=='iteration':bad['examples']['checks'].pop()
    elif change=='onboarding':bad['onboarding']['viewer_iteration']=False
    elif change=='onboarding-source':bad['onboarding']['source_snapshot_sha256']='0'*64
    elif change=='physics-coverage':bad['verification']['suites']['current-physics-and-workflow']['required_module_coverage']['test_modal_solver']['skipped']=1
    else:bad['licenses']['project_license']='MIT'
    with pytest.raises(ValueError):validate_receipt(root,__version__,bad)


@pytest.mark.parametrize('kind',['home','binary','private-key'])
def test_public_scan_rejects_accidental_personal_content(public_source,kind):
    root,_=public_source
    if kind=='home':(root/'references/leak.md').write_text('C:'+chr(92)+'Users'+chr(92)+'private-person'+chr(92)+'model.step')
    elif kind=='binary':(root/'assets/ccx.exe').write_bytes(b'fixture')
    else:(root/'assets/private.txt').write_text('-----BEGIN '+'PRIVATE KEY-----')
    with pytest.raises(ValueError):scan_public_files(root)


def test_preview_iteration_preserves_task_and_gates():
    folder=ROOT/'examples/preview'
    read=lambda n:json.loads((folder/(n+'.case.json')).read_text(encoding='utf-8'))
    failed,improved=read('fail'),read('iteration')
    assert structural_contract(failed)==structural_contract(improved)
    assert failed['model']!=improved['model']
    assert all(not any(read(n)['conditions'].values()) for n in ('pass','fail','indeterminate','iteration'))


def release_fixture(root, receipt):
    """Synthetic evidence validates packaging guards, never numerical accuracy."""
    release=copy.deepcopy(receipt)
    release.update(toolkit_version='1.6.0',channel='release')
    release['release_readiness']={
        'source_snapshot_sha256':snapshot_digest(root),'passed':True,'open_release_blockers':[],
        'areas':{k:{'passed':True,'evidence':['synthetic receipt-integrity fixture']}
                 for k in ('agent_workflow','calculation_display','resources','exceptions_gates',
                           'product_review','documentation_licenses')},
        'platforms':{k:{'passed':True,'environment':'synthetic','evidence':['fixture'],
                        **{c:True for c in ('fresh_install','cli','worker','viewer_iteration','compact_storage','regression')}}
                     for k in ('Windows','Ubuntu')},
        'agents':{k:{'discovery_install_checked':True,'portable_cli_checked':True,
                      'live_agent_session_tested':False,'evidence':['fixture']}
                  for k in ('codex','claude','deepseek','omp','pi')},
        'showcases':{k:{'workflow_verified':True,'whole_product_pass_available':False,'evidence':['fixture']}
                     for k in ('thermal_bridge','inspection_arm','sensor_mast')},
    }
    return release


def test_public_release_uses_current_source_contract_not_private_history(public_source):
    root,receipt=public_source
    release=release_fixture(root,receipt)
    write_json(root/'validation/public-release.json',release)
    assert check_public_qualification(root,'1.6.0')['channel']=='release'
    from simplecae.release import check_qualification
    assert check_qualification(root,'1.6.0')['channel']=='release'
    # A supported discovery path must not be misrepresented as a live model run.
    assert not release['release_readiness']['agents']['pi']['live_agent_session_tested']


@pytest.mark.parametrize('missing',['platform','fresh-install','host','host-scope','showcase','product',
                                    'audit-area','blocker','snapshot','dev-version'])
def test_final_release_cannot_be_promoted_from_partial_preview(public_source,missing):
    root,receipt=public_source
    release=release_fixture(root,receipt);ready=release['release_readiness'];version='1.6.0'
    if missing=='platform':ready['platforms'].pop('Ubuntu')
    elif missing=='fresh-install':ready['platforms']['Windows']['fresh_install']=False
    elif missing=='host':ready['agents'].pop('omp')
    elif missing=='host-scope':ready['agents']['pi'].pop('live_agent_session_tested')
    elif missing=='showcase':ready['showcases'].pop('inspection_arm')
    elif missing=='product':ready['showcases']['sensor_mast']['whole_product_pass_available']=True
    elif missing=='audit-area':ready['areas'].pop('exceptions_gates')
    elif missing=='blocker':ready['open_release_blockers']=['unresolved install failure']
    elif missing=='snapshot':ready['source_snapshot_sha256']='0'*64
    elif missing=='dev-version':version=release['toolkit_version']='1.6.0.dev12'
    with pytest.raises(ValueError):
        validate_receipt(root,version,release)
