import pytest
from simplecae.schemas import check_contract,ContractError
from simplecae.use_plan import validate_plan


def test_missing_case_field_has_located_syntax_example():
    with pytest.raises(ContractError) as error:
        check_contract({'schema_version':'2.0'})
    hints=error.value.details['repair_hints']
    assert any(h['path']=='$.mesh' and 'sizes_mm' in h['legal_shape_example'] for h in hints)
    assert all('Syntax example' in h.get('meaning','') for h in hints)
