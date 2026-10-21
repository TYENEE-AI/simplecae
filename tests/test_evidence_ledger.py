import copy,json
import pytest
from simplecae.evidence import init_ledger,inspect_ledger,review_ledger
from simplecae.case import sha256,write_json


def ledger(tmp_path,kind='software_test',state='calculated'):
    model=tmp_path/'model.step';model.write_text('revision A')
    evidence=tmp_path/'record.json';evidence.write_text('externally supplied record')
    path=tmp_path/'ledger.json';init_ledger([model],path,'Example')
    c=json.loads(path.read_text(encoding='utf-8'));item=next(i for i in c['items'] if i['domain']=='control')
    item.update(state=state,statement='36 states checked; no physical control validation')
    ref={'file':{'path':'record.json','sha256':sha256(evidence)},'kind':kind,'applies_to':['source1'],
         'source_sha256':{'source1':sha256(model)},'scope':'Only the explicitly supplied record'}
    if kind.startswith('physical_'):ref.update(outcome='fail',date='2026-10-14',operator='test operator',test_method='specified bench procedure')
    item['evidence']=[ref];write_json(path,c)
    return path,c,model,evidence


def control(record):return next(i for i in record['items'] if i['domain']=='control')


def test_software_result_is_calculated_and_never_physical_certification(tmp_path):
    p,_,_,_=ledger(tmp_path);r=inspect_ledger(p)
    assert control(r)['effective_state']=='calculated'
    assert not r['whole_product_rating_available'] and not r['certification_available']
    assert control(r)['physical_outcomes']==[]


def test_physical_fail_is_recorded_without_becoming_verified_or_pass(tmp_path):
    p,_,_,_=ledger(tmp_path,'physical_test','physical_recorded');r=inspect_ledger(p)
    assert control(r)['effective_state']=='physical_recorded'
    assert control(r)['physical_outcomes']==['fail']
    assert not control(r)['physical_measurement_independently_verified']
    output=review_ledger(p,tmp_path/'review')
    page=(tmp_path/'review/evidence.html').read_text(encoding='utf-8')
    assert '实测结果 fail' in page and '产品认证' in page and 'record.json' in page
    assert 'evidence-files/' in page and len(list((tmp_path/'review/evidence-files').glob('*')))==1


def test_software_build_cannot_be_relabelled_physical(tmp_path):
    p,_,_,_=ledger(tmp_path,'software_build','physical_recorded')
    with pytest.raises(ValueError,match='physical_recorded cannot'):inspect_ledger(p)


@pytest.mark.parametrize('changed',['model','evidence','missing'])
def test_changed_or_missing_files_invalidate_usable_claim(tmp_path,changed):
    p,_,model,evidence=ledger(tmp_path,'physical_test','physical_recorded')
    if changed=='model':model.write_text('revision B')
    elif changed=='evidence':evidence.write_text('changed record')
    else:evidence.unlink()
    item=control(inspect_ledger(p));assert item['effective_state']=='evidence_missing_or_stale'
    assert item['declared_state']=='physical_recorded' and item['physical_outcomes']==[]


def test_rebinding_new_design_does_not_retarget_old_physical_record(tmp_path):
    p,c,model,_=ledger(tmp_path,'physical_test','physical_recorded');model.write_text('revision B')
    c['bindings']['source1']['sha256']=sha256(model);write_json(p,c)
    r=inspect_ledger(p);assert r['bindings']['source1']['status']=='current'
    assert control(r)['effective_state']=='evidence_missing_or_stale'


def test_omitted_domains_are_unassessed_and_no_overwriting(tmp_path):
    p,c,_,_=ledger(tmp_path);c['items']=[c['items'][8]];write_json(p,c)
    r=inspect_ledger(p);assert len(r['unlisted_domains'])==11 and len(r['items'])==12
    assert all(i['effective_state']=='unassessed' for i in r['items'] if i['domain']!='control')
    with pytest.raises(ValueError,match='already exists'):init_ledger([p],p)


def test_physical_record_requires_protocol_operator_outcome_and_source_snapshot(tmp_path):
    p,c,_,_=ledger(tmp_path,'physical_test','physical_recorded');original=copy.deepcopy(c)
    for field in ('test_method','operator','date','outcome','source_sha256'):
        candidate=copy.deepcopy(original);del candidate['items'][8]['evidence'][0][field];write_json(p,candidate)
        with pytest.raises(ValueError):inspect_ledger(p)
