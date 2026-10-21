import copy,json
import numpy as np
import pytest
from simplecae.level_cache import level_key,write_state,restore,save
from simplecae.case import write_json
from simplecae.benchmarks import bar_case
from simplecae import level_cache


def test_mesh_list_can_extend_but_exact_physics_and_tools_must_match(tmp_path):
    step=tmp_path/'part.step';step.write_text('geometry A');exe=tmp_path/'ccx';exe.write_text('solver A')
    c=bar_case('part',[1000.,0,0],[5.,4.,3.]);c['model']['path']=str(step)
    key=level_key(c,3.,exe);extended=copy.deepcopy(c);extended['mesh']['sizes_mm']=[5.,4.,3.,2.]
    assert level_key(extended,3.,exe)==key
    for field in ('load','criteria','support','material','probe','mesh-limit'):
        changed=copy.deepcopy(extended)
        if field=='load':changed['loads'][0]['total_force_n'][0]+=1e-9
        elif field=='criteria':changed['criteria']['max_displacement_mm']=.2
        elif field=='support':changed['supports'][0]['dofs']=[1,3]
        elif field=='material':changed['material']['youngs_modulus_mpa']+=.001
        elif field=='probe':changed['probes']=[{'name':'tip','type':'point','point_mm':[100,0,0]}]
        else:changed['mesh']['max_elements']=10000
        assert level_key(changed,3.,exe)!=key
    exe.write_text('solver B');assert level_key(c,3.,exe)!=key
    exe.write_text('solver A');step.write_text('geometry B');assert level_key(c,3.,exe)!=key


def solved(tmp_path):
    d=tmp_path/'level';d.mkdir();xyz={n:np.array([n,0,0.]) for n in range(1,11)}
    mesh=(xyz,{1:list(xyz)},[1],{10:np.array([1.,0,0])},{'node_count':10,'element_count':1})
    write_state(mesh,d)
    np.savez(d/'mesh.npz',node_ids=list(xyz),xyz=list(xyz.values()))
    for file in ('job.inp','job.dat','job.frd','job.solver.log'):(d/file).write_text('fixture: read/restore test, not native evidence')
    level={'mesh':mesh[-1],'results':{'force_balance_relative_error':0.,'moment_balance_relative_error':0.},'directory':str(d),'created_at_utc':'original'}
    write_json(d/'results.json',level);assert save(tmp_path/'cache','key',d,level,5e-4)
    return d,mesh,level


def test_level_restores_without_rewriting_original_and_paths_relocate(tmp_path):
    d,mesh,_=solved(tmp_path);before=(d/'results.json').read_bytes();out=tmp_path/'new'
    restored,level=restore(tmp_path/'cache','key',out)
    assert level['directory']==str(out) and level['level_reuse']['numerical_evidence_created_at_utc']=='original'
    assert restored[1]==mesh[1] and np.allclose(restored[3][10],[1,0,0])
    assert (d/'results.json').read_bytes()==before


def test_corrupt_or_incomplete_level_is_miss_and_does_not_fill_output(tmp_path):
    solved(tmp_path);folder=tmp_path/'cache/levels/key';index=json.loads((folder/'latest.json').read_text())
    (folder/index['directory']/'job.dat').write_text('tampered')
    out=tmp_path/'new';assert restore(tmp_path/'cache','key',out) is None and not out.exists()


def test_level_restore_io_failure_cannot_fall_through_to_solver(tmp_path,monkeypatch):
    solved(tmp_path)
    def failure(*args,**kwargs):raise OSError('disk full')
    monkeypatch.setattr(level_cache.shutil,'copytree',failure)
    with pytest.raises(OSError,match='disk full'):restore(tmp_path/'cache','key',tmp_path/'new')


def test_unbalanced_level_not_saved(tmp_path):
    d,_,level=solved(tmp_path);level['results']['force_balance_relative_error']=.01
    assert not save(tmp_path/'other','key',d,level,5e-4)
    assert not (tmp_path/'other').exists()
