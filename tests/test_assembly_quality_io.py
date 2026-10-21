"""Element quality stays source-bound without repeated archive decompression."""
from collections import Counter
from pathlib import Path
import numpy as np
import pytest
from simplecae.assembly import load_assembly_case,make_assembly_mesh

ROOT=Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('size',[5.,4.])
def test_quality_arrays_read_once_per_body_and_preserve_every_element(tmp_path,monkeypatch,size):
    original=np.load;reads=Counter()
    class Archive:
        def __init__(self,path,*args,**kwargs):
            self.path=Path(path);self.archive=original(path,*args,**kwargs)
        def __getitem__(self,key):
            reads[self.path,key]+=1
            return self.archive[key]
        def __getattr__(self,name):return getattr(self.archive,name)
        def __enter__(self):return self
        def __exit__(self,*_):self.archive.close()
    monkeypatch.setattr(np,'load',Archive)
    case=load_assembly_case(ROOT/'examples/assemblies/bonded.case.json')
    out=tmp_path/'mesh';out.mkdir()
    _,_,_,_,meta=make_assembly_mesh(case,size,out)
    offset=0;expected={key:{} for key in ('element_min_sicn','element_min_det_jac')}
    for body in meta['body_reports']:
        path=Path(body['directory'])/'mesh.npz'
        with original(path) as source:
            ids=list(map(int,source['element_ids']));index={e:i for i,e in enumerate(ids)}
            for key in expected:
                assert reads[path,key]==1
                values=source[key]
                expected[key].update({offset+i+1:float(values[index[e]]) for i,e in enumerate(sorted(ids))})
            offset+=len(ids)
    with original(out/'mesh.npz') as merged:
        ids=list(map(int,merged['element_ids']))
        for key,table in expected.items():
            assert dict(zip(ids,map(float,merged[key])))==table
