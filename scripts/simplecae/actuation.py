"""Explicit internal drive/reaction pairs. Rigid URDF joints are not motors.

The declared pairs reroute support wrenches; they never replace the original
virtual-work effort used for actuator rating. Prismatic pairs must be axial.
"""
import numpy as np
from .case import keys, vector


def validate_reactions(case):
    declarations = case.get('actuation_reactions', [])
    if not isinstance(declarations, list):
        raise ValueError('actuation_reactions must be a list')
    names, joints = set(), set()
    for item in declarations:
        keys(item, ['name', 'joint', 'driven', 'reaction', 'verified', 'reference'],
             ['name', 'joint', 'driven', 'reaction'], 'actuation reaction')
        for key in ('name', 'joint'):
            if not isinstance(item[key], str) or not item[key]:
                raise ValueError('actuation name/joint must be nonempty strings')
        if item['name'] in names or item['joint'] in joints:
            raise ValueError('actuation names and independent joints must be unique')
        names.add(item['name']); joints.add(item['joint'])
        for side in ('driven', 'reaction'):
            port = item[side]
            keys(port, ['link', 'point_link_m'], ['link', 'point_link_m'], 'actuation port')
            if not isinstance(port['link'], str) or not port['link']:
                raise ValueError('actuation port needs a nonempty link')
            vector(port['point_link_m'], 'actuation attachment point')
        if 'verified' in item and type(item['verified']) is not bool:
            raise ValueError('actuation verified must be boolean')
        if 'reference' in item and (not isinstance(item['reference'], str) or not item['reference'].strip()):
            raise ValueError('actuation reference must be nonempty')
        if item.get('verified') and not item.get('reference'):
            raise ValueError('verified actuation path requires an evidence reference')
    reserved = {'actuation:'+item['name']+':'+side for item in declarations for side in ('driven','reaction')}
    if reserved & {p['name'] for field in ('loads','payloads') for p in case.get(field, [])}:
        raise ValueError('external load name collides with a generated actuation port')


def closed_statics(robot, case, kin, bare, *, fixed=False):
    from .robot import static_wrenches
    validate_reactions(case)
    generated = []; pairs = []
    for item in case.get('actuation_reactions', []):
        name = item['joint']; joint = robot['joints'].get(name)
        if joint is None or joint['type']=='fixed' or joint['mimic']:
            raise ValueError('reaction path must name an independent moving joint')
        if any(j != name and driver == name and abs(coefficient)>1e-12
               for j, (driver, coefficient) in kin['drivers'].items()):
            raise ValueError('mimic transmission reaction distribution needs an explicit transmission model')
        downstream = set()
        def walk(link):
            downstream.add(link)
            for j in robot['children'][link]:walk(robot['joints'][j]['child'])
        walk(joint['child'])
        if item['driven']['link'] not in downstream:
            raise ValueError('driven attachment must lie in its joint child subtree')
        if item['reaction']['link'] not in robot['links'] or item['reaction']['link'] in downstream:
            raise ValueError('reaction attachment must be a known link outside the driven subtree')
        axis = kin['axes'][name]; effort = bare['actuator_efforts'][name]
        points = {side:kin['frames'][item[side]['link']][:3,:3]@np.asarray(item[side]['point_link_m'])
                  +kin['frames'][item[side]['link']][:3,3] for side in ('driven','reaction')}
        if joint['type']=='prismatic':
            separation = points['driven']-points['reaction']
            if np.linalg.norm(np.cross(separation,axis)) > 1e-10+1e-8*np.linalg.norm(separation):
                raise ValueError('prismatic drive/reaction attachments are off-axis; declare a transmission instead of inventing a balancing couple')
            force, moment = axis*effort, np.zeros(3)
        else:
            force, moment = np.zeros(3), axis*effort
        ports = []
        for side, sign in (('driven',1),('reaction',-1)):
            port = {'name':'actuation:'+item['name']+':'+side,'link':item[side]['link'],
                    'position_m':points[side].tolist(),'force_n':(force*sign).tolist(),
                    'moment_n_m':(moment*sign).tolist(),'frame':'world','position_frame':'world','scalable':False}
            generated.append(port); ports.append(port)
        resultant = sum((np.r_[p['force_n'],np.asarray(p['moment_n_m'])+np.cross(p['position_m'],p['force_n'])] for p in ports),np.zeros(6))
        if np.linalg.norm(resultant)>1e-9*max(abs(effort),1):
            raise RuntimeError('internal actuation pair failed independent world force/moment closure')
        pairs.append({'name':item['name'],'joint':name,'type':joint['type'],'holding_effort':effort,
                      'ports':ports,'world_pair_resultant':resultant.tolist(),
                      'verified':item.get('verified',False),'reference':item.get('reference')})
    if generated:
        payloads=[p for p in case.get('payloads',[]) if not fixed or not p.get('scalable',True)]
        loads=[p for p in case.get('loads',[]) if not fixed or not p.get('scalable',True)]
        result=static_wrenches(robot,kin,case['gravity_m_s2'],payloads,loads+generated)
        if not np.allclose(result['world_external_wrench'],bare['world_external_wrench'],atol=1e-9,rtol=1e-10):
            raise RuntimeError('internal drive changed external equilibrium')
    else:result=dict(bare)
    routed={p['joint'] for p in pairs}
    for joint, effort in result['actuator_efforts'].items():
        expected=0. if joint in routed else bare['actuator_efforts'][joint]
        if not np.isclose(effort,expected,atol=1e-9,rtol=1e-9):
            raise ValueError('declared reaction path couples another moving joint or does not balance its driven joint; an explicit transmission model is required')
    result['actuation_loads']=generated
    result['reaction_paths']=pairs
    result['unrouted_actuators']=sorted(set(bare['actuator_efforts'])-routed)
    return result


def reaction_summary(full):
    pairs=full.get('reaction_paths',[])
    return {'declared':bool(pairs),'pairs':pairs,'unrouted_actuators':full.get('unrouted_actuators',[]),
            'declared_paths_verified':bool(pairs) and all(p['verified'] for p in pairs),
            'scope':'Declared axial force or direct torque pairs only; bearing contact, transmission strength and component stiffness are not inferred.'}
