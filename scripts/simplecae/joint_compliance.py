"""Independent scalar joint springs at a fixed, statically determinate pose.

Use external generalized effort (opposite the holding effort), not a controller
rating, as the spring load. Off-axis directions remain explicitly ideal rigid.
"""
import numpy as np
from .case import keys, number

ROTATIONAL = 'rotational_stiffness_n_m_rad'
LINEAR = 'linear_stiffness_n_m'


def enabled(case):
    return 'joint_compliance' in case.get('elastic_transfer', {})


def validate(case, robot=None):
    if not enabled(case):
        if 'rigid_joints' in case.get('elastic_transfer', {}):
            raise ValueError('rigid_joints requires explicit joint_compliance')
        return
    spec = case['elastic_transfer']; springs = spec['joint_compliance']
    if not isinstance(springs, dict) or not springs:
        raise ValueError('joint_compliance needs a nonempty joint-name mapping')
    rigid = spec.get('rigid_joints')
    if not isinstance(rigid, list) or any(not isinstance(n, str) or not n for n in rigid) or len(set(rigid)) != len(rigid):
        raise ValueError('joint compliance needs explicit unique rigid_joints, including fixed joints')
    if set(rigid) & set(springs): raise ValueError('a joint cannot be both compliant and rigid')
    for name, spring in springs.items():
        if not isinstance(name, str) or not name: raise ValueError('joint names must be nonempty')
        keys(spring, [ROTATIONAL, LINEAR, 'reference', 'verified'], ['reference', 'verified'], 'joint spring')
        stiffness = [k for k in (ROTATIONAL, LINEAR) if k in spring]
        if len(stiffness) != 1: raise ValueError('supply exactly one stiffness with explicit units per joint')
        number(spring[stiffness[0]], 'joint stiffness', True)
        if type(spring['verified']) is not bool: raise ValueError('joint verified must be boolean')
        if not isinstance(spring['reference'], str) or not spring['reference'].strip():
            raise ValueError('joint stiffness needs source and operating-state applicability')
    if robot is None: return
    if set(rigid) | set(springs) != set(robot['joints']):
        raise ValueError('every URDF joint must be explicitly compliant or rigid; unknown joints are rejected')
    if any(j.get('mimic') for j in robot['joints'].values()):
        raise ValueError('joint compliance does not support mimic/coupled drive coordinates')
    for name, spring in springs.items():
        kind = robot['joints'][name]['type']
        expected = LINEAR if kind == 'prismatic' else ROTATIONAL
        if kind == 'fixed' or expected not in spring:
            raise ValueError('joint stiffness units/type must match an independent moving URDF joint: '+name)


def solve(case, robot, kin, fixed=False):
    """Return world-mm/rad relative motions at child origins and raw evidence."""
    from .robot import static_wrenches
    payloads = [p for p in case.get('payloads', []) if not fixed or not p.get('scalable', True)]
    loads = [p for p in case.get('loads', []) if not fixed or not p.get('scalable', True)]
    statics = static_wrenches(robot, kin, case['gravity_m_s2'], payloads, loads)
    motions = {}; records = []
    points = [t[:3, 3] for t in kin['frames'].values()]
    points += [kin['frames'][name][:3,:3]@link['com_m']+kin['frames'][name][:3,3] for name,link in robot['links'].items()]
    for load in case.get('loads', []):
        p=np.array(load.get('position_m',[0,0,0]));t=kin['frames'][load['link']]
        points.append(p if load.get('position_frame',load.get('frame','link'))=='world' else t[:3,:3]@p+t[:3,3])
    for payload in case.get('payloads', []):
        t=kin['frames'][payload['link']];points.append(t[:3,:3]@np.array(payload['center_m'])+t[:3,3])
    origins = np.array(points)
    # Maximum declared-point separation is invariant under world-frame rotation;
    # an axis-aligned box diagonal would change an applicability gate with yaw.
    span_mm = max(max(float(np.linalg.norm(origins-p,axis=1).max()) for p in origins)*1000, 1.)
    passed = True
    for name, spring in case['elastic_transfer']['joint_compliance'].items():
        joint = robot['joints'][name]; axis = kin['axes'][name]
        linear = joint['type'] == 'prismatic'; key = LINEAR if linear else ROTATIONAL
        wrench = statics['joint_wrenches'][name]
        effort = float(axis @ (wrench[:3] if linear else wrench[3:]))
        delta = effort / spring[key]
        theta = np.zeros(3) if linear else axis*delta
        offset = (kin['frames'][joint['child']][:3,3]-kin['joint_frames'][name][:3,3])*1000
        translation = axis*delta*1000 if linear else np.cross(theta, offset)
        ok = abs(delta)*1000 <= .01*span_mm if linear else abs(delta) <= case['elastic_transfer']['max_rotation_rad']
        passed = passed and ok
        motions[name] = (translation, theta)
        records.append({'joint':name, 'type':joint['type'], key:spring[key], 'external_generalized_effort':effort,
                        'effort_units':'N' if linear else 'N m', 'deflection':delta, 'deflection_units':'m' if linear else 'rad',
                        'axis_world':axis.tolist(), 'translation_world_mm':translation.tolist(), 'rotation_world_rad':theta.tolist(),
                        'small_response_passed':bool(ok), 'linear_screen_span_mm':span_mm,
                        'reference':spring['reference'], 'verified':spring['verified']})
    return motions, records, bool(passed)


def evidence_matches(case, evidence):
    """Missing or inconsistent spring output cannot inherit a link-only pass."""
    if not enabled(case): return True
    springs = case['elastic_transfer']['joint_compliance']
    if not evidence or not evidence.get('small_response_passed'): return False
    try:
        for stage in ('full', 'fixed'):
            records = evidence[stage]
            if len(records) != len(springs) or {r['joint'] for r in records} != set(springs): return False
            for r in records:
                s = springs[r['joint']]; key = LINEAR if LINEAR in s else ROTATIONAL
                values = [r[key], r['external_generalized_effort'], r['deflection']]
                if not all(np.isfinite(v) for v in values) or r[key] != s[key] or not r['small_response_passed']: return False
                if not np.isclose(r['deflection'], r['external_generalized_effort']/s[key], rtol=1e-10, atol=1e-15): return False
                if r['verified'] != s['verified'] or r['reference'] != s['reference']: return False
                if r['deflection_units'] != ('m' if key == LINEAR else 'rad'): return False
    except (KeyError, TypeError, ValueError): return False
    return True
