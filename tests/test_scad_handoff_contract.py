"""Exporter failures must be actionable without loading either native runtime."""
import subprocess
import sys
from pathlib import Path
import pytest
from simplecae_scad import export_for_cae, HandoffError


def test_package_is_not_a_selection_source(tmp_path):
    with pytest.raises(HandoffError,match='Rerun its source notebook') as error:
        export_for_cae(tmp_path/'part.scadpkg',tmp_path/'out',required={'interface.mount':{'face_count':1}})
    assert error.value.code=='rerun_source_notebook'
    assert not (tmp_path/'out').exists()


@pytest.mark.parametrize('required', [{}, {'cae.mount':{'face_count':1}}, {'interface.mount':{}},
                                    {'interface.mount':{'face_count':True}},
                                    {'interface.mount':{'face_count':1,'surface_types':'Plane'}}])
def test_invalid_required_contract_fails_before_export(tmp_path,required):
    with pytest.raises(HandoffError):export_for_cae(object(),tmp_path/'out',required=required)
    assert not (tmp_path/'out').exists()


def test_import_does_not_load_solver_or_cad_runtime():
    scripts=Path(__file__).resolve().parents[1]/'scripts'
    result=subprocess.run([sys.executable,'-c',
        f"import sys;sys.path.insert(0,{str(scripts)!r});import simplecae_scad;assert not any(n in sys.modules for n in ['gmsh','numpy','scipy','OCP','simplecadapi','simplecae'])"],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
