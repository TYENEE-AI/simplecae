"""Explanatory axis-aligned support recipes; no inferred physical mounting."""
from .case import selector as validate_selector

PRESETS={
 'fixed':{'label':'整面固定','meaning':'所选各节点X/Y/Z位移均受限；适用于明确的刚性固定理想化。','axis_role':None},
 'normal_seat':{'label':'法向座面近似','meaning':'仅限制指定轴位移；座面法向须与该分析/世界轴一致。拉压均被限制，没有分离接触模型。','axis_role':'normal'},
 'sliding_guide':{'label':'直线导轨近似','meaning':'限制滑动轴以外的两个位移分量；仍需要真实轴向限位或驱动。转动约束取决于所选区域分布。','axis_role':'sliding'},
 'pin_position':{'label':'销位两方向近似','meaning':'限制销轴以外的两个位移分量；可能锁住转动，不能直接当作有间隙的自由转动销接。','axis_role':'pin'},
 'axial_stop':{'label':'轴向限位近似','meaning':'只限制指定轴位移；没有单向脱离、间隙、预紧或摩擦。','axis_role':'stop'}
}


def support_from_preset(name,selected,preset,axis=None,*,body=None):
    if not isinstance(name,str) or not name.strip():raise ValueError('support needs a nonempty name')
    validate_selector(selected)
    if preset not in PRESETS:raise ValueError('unknown support preset')
    if preset=='fixed':
        if axis is not None:raise ValueError('fixed preset has no directional axis')
        dofs=[1,2,3]
    else:
        if axis not in ('x','y','z'):raise ValueError('support preset needs analysis/world axis x/y/z; arbitrary directions require an explicitly rotated analysis frame or a more detailed connection model')
        component='xyz'.index(axis)+1
        dofs=[component] if preset in ('normal_seat','axial_stop') else [d for d in (1,2,3) if d!=component]
    result={'name':name,'selector':selected,'dofs':dofs}
    if body is not None:
        if not isinstance(body,str) or not body:raise ValueError('assembly support body must be nonempty')
        result['body']=body
    return result
