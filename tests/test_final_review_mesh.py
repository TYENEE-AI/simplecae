import numpy as np
import pytest
import trimesh

from simplecae.mesh_input import check_self_intersection
from simplecae.diagnostics import WorkflowError


def pair(vertices, faces):
    return trimesh.Trimesh(vertices=vertices, faces=faces, process=False)


@pytest.mark.parametrize('scale', [1e-3, 1, 1e3])
def test_sliver_shared_edge_is_not_intersection(scale):
    mesh = pair(np.array([[0,0,0], [100,0,0], [100,.00001,0], [0,-.00001,0]])*scale,
                [[0,1,2], [1,0,3]])
    assert check_self_intersection(mesh)['passed']
    with pytest.raises(ValueError, match='intersecting'):
        check_self_intersection(mesh, algorithm='legacy')


@pytest.mark.parametrize('vertices,faces', [
    ([[0,0,0],[2,0,0],[0,2,0],[1,1,0]], [[0,1,2],[0,1,3]]),
    ([[0,0,0],[2,0,0],[0,2,0],[1,0,0],[0,1,0]], [[0,1,2],[0,3,4]]),
    ([[0,0,0],[2,0,0],[0,2,0],[1,1,-1],[1,1,1]], [[0,1,2],[0,3,4]]),
    ([[0,0,0],[2,0,0],[0,2,0]], [[0,1,2],[2,1,0]]),
])
def test_fold_shared_vertex_crossing_and_duplicate_rejected(vertices, faces):
    with pytest.raises(WorkflowError) as error:
        check_self_intersection(pair(vertices, faces))
    details=error.value.diagnostic['details']
    assert len(details['coordinates_mm']) == 2
    assert min(details['areas_mm2']) > 0


@pytest.mark.parametrize('second', [ [[-1,0,0],[0,-1,0]], [[1,0,1],[0,1,1]], [[0,0,1],[0,-1,1]] ])
def test_vertex_only_touch_allowed(second):
    assert check_self_intersection(pair([[0,0,0],[1,0,0],[0,1,0]]+second, [[0,1,2],[0,3,4]]))['passed']


def test_overlapping_cubes_rejected():
    first=trimesh.creation.box()
    second=trimesh.creation.box();second.apply_translation([.4,.3,.2])
    with pytest.raises(ValueError, match='intersecting'):
        check_self_intersection(trimesh.util.concatenate([first,second]))
