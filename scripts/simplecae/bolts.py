"""Fixed-axis equivalent axial bolts, with a force-controlled then locked adjustment.

Energy = k/2 * (a.(u_slave-u_master) + q)^2. The generalized adjustment q
is loaded during tightening and frozen afterwards; bolt force can still change.
No threaded geometry, shear/bending stiffness or tightening-torque inference.
"""
from pathlib import Path
import re
import numpy as np
from .case import keys,number,vector,selector


def validate(case):
    bolts=case.get('bolts',[])
    if not isinstance(bolts,list):raise ValueError('bolts must be a list')
    names=[];bodies={b['name'] for b in case['bodies']}
    for b in bolts:
        fields=['name','master','slave','axis','axial_stiffness_n_mm','preload_n','allowable_tension_n','reference']
        keys(b,fields,fields,'equivalent axial bolt');names.append(b['name'])
        if not isinstance(b['name'],str) or not b['name'].strip():raise ValueError('bolt name must be nonempty')
        if not isinstance(b['reference'],str) or not b['reference'].strip():raise ValueError('bolt stiffness/preload/allowable need a source and applicability reference')
        for role in ('master','slave'):
            keys(b[role],['body','selector'],['body','selector'],'bolt attachment')
            if b[role]['body'] not in bodies:raise ValueError('bolt references unknown body')
            selector(b[role]['selector'])
        if b['master']['body']==b['slave']['body']:raise ValueError('bolt needs distinct bodies')
        axis=vector(b['axis'],'bolt axis')
        if abs(np.linalg.norm(axis)-1)>1e-8:raise ValueError('bolt axis must be a world-axis unit vector')
        for field in ('axial_stiffness_n_mm','preload_n','allowable_tension_n'):number(b[field],field,True)
    if len(names)!=len(set(names)):raise ValueError('bolt names must be unique')
    if bolts:
        from .contact import enabled
        if not enabled(case):raise ValueError('locked bolt model requires explicit planar contact; no implicit clamped joint')


def attachment(side,coords,body_data):
    from .geometry import select_faces
    from .assembly import quadrature,tri_basis
    data=body_data[side['body']];faces=select_faces(data['local_geometry'],side['selector'])
    triangles=[t for f in faces for t in data['surfaces'][f]]
    weights={};area=0.;normal=None
    for nodes in triangles:
        xyz=np.array([coords[n] for n in nodes])
        n=np.cross(xyz[1]-xyz[0],xyz[2]-xyz[0]);n/=np.linalg.norm(n)
        if normal is None:normal=n
        if abs(n@normal)<1-1e-8:raise ValueError('bolt attachment must be planar')
        for r,s,w in quadrature():
            basis,dr,ds=tri_basis(r,s);measure=np.linalg.norm(np.cross(dr@xyz,ds@xyz))*w/2;area+=measure
            for node,value in zip(nodes,basis):weights[node]=weights.get(node,0.)+float(value*measure)
    if not area:raise ValueError('empty bolt attachment')
    weights={n:v/area for n,v in weights.items() if abs(v/area)>1e-14}
    center=sum((coords[n]*v for n,v in weights.items()),np.zeros(3));mesh_center=center.copy()
    # A curved FE boundary approximates the CAD circle and its centroid. Keep
    # the resultant at the declared CAD port centroid instead of silently
    # introducing an eccentric bolt or relaxing the coaxiality check.
    records=[f for f in data['local_geometry']['faces'] if f['id'] in faces]
    if records and all('area_mm2' in f and 'centroid_mm' in f for f in records):
        from .robot import rotation_rpy
        placement=data.get('placement',{'rpy_rad':[0,0,0],'translation_mm':[0,0,0]})
        target=rotation_rpy(placement['rpy_rad'])@sum((f['area_mm2']*np.array(f['centroid_mm']) for f in records),np.zeros(3))/sum(f['area_mm2'] for f in records)+placement['translation_mm']
        nodes=list(weights);positions=np.array([coords[n] for n in nodes]);scale=max(np.linalg.norm(np.ptp(positions,axis=0)),1.)
        matrix=np.vstack((np.ones(len(nodes)),((positions-center)/scale).T))
        rhs=np.r_[0.,(target-center)/scale]
        correction=np.linalg.lstsq(matrix,rhs,rcond=None)[0]
        if np.linalg.norm(matrix@correction-rhs)>1e-10:raise ValueError('bolt port cannot reproduce its CAD centroid')
        weights={n:weights[n]+float(v) for n,v in zip(nodes,correction)}
        center=sum((coords[n]*v for n,v in weights.items()),np.zeros(3))
        if abs(sum(weights.values())-1)>1e-10 or np.linalg.norm(center-target)>1e-8:raise ValueError('bolt port force/moment consistency failed')
    points=np.array([coords[n] for n in weights])
    if np.max(abs((points-center)@normal))>1e-8:raise ValueError('bolt attachment patches are not coplanar')
    return {'weights':weights,'center':center,'normal':normal,'area_mm2':area,
            'cad_centroid_correction_mm':float(np.linalg.norm(center-mesh_center))}


def compile_bolts(case,coords,body_data,connections,node_start,element_start):
    records=[];node=node_start;elem=element_start
    for spec in case.get('bolts',[]):
        a=np.array(spec['axis']);ports={r:attachment(spec[r],coords,body_data) for r in ('master','slave')}
        delta=ports['slave']['center']-ports['master']['center'];length=float(a@delta)
        if length<=0 or np.linalg.norm(delta-length*a)>1e-7*max(length,1.):raise ValueError('bolt attachment centroids must lie on its positive axis')
        if any(abs(a@p['normal'])<1-1e-8 for p in ports.values()):raise ValueError('bolt axis must be normal to its attachment patches')
        node+=2;elem+=1;stretch,adjust=node-1,node
        connections['auxiliary_nodes'].update({str(stretch):ports['slave']['center'].tolist(),str(adjust):ports['master']['center'].tolist()})
        terms=[(stretch,1,1.),(adjust,1,-1.)]
        for role,sign in [('slave',-1.),('master',1.)]:
            terms += [(int(n),i+1,float(sign*v*a[i])) for n,v in ports[role]['weights'].items() for i in range(3) if abs(v*a[i])>1e-14]
        connections['equations'].append(terms)
        connections['springs'].append({'node':stretch,'element':elem,'stiffness_n_mm':spec['axial_stiffness_n_mm'],'connection':spec['name']})
        records.append({'name':spec['name'],'stretch_node':stretch,'adjustment_node':adjust,'stiffness_n_mm':spec['axial_stiffness_n_mm'],
                        'preload_n':spec['preload_n'],'allowable_tension_n':spec['allowable_tension_n'],'axis':a.tolist(),'span_mm':length,
                        'ports':{r:{'weights':p['weights'],'center_mm':p['center'].tolist(),'area_mm2':p['area_mm2'],
                                    'cad_centroid_correction_mm':p['cad_centroid_correction_mm']} for r,p in ports.items()}})
    connections['bolts']=records


def native_roundoff(token):
    # CalculiX DAT prints six decimal places in scientific notation. Plain
    # literals in synthetic/reference inputs are treated as exact, not given
    # a large, guessed rounding allowance.
    value=token.replace('D','E').replace('d','e')
    m=re.fullmatch(r'([+-]?\d+\.)(\d{6,})[eE]([+-]?\d+)',value)
    if not m:
        m=re.fullmatch(r'([+-]?\d+\.)(\d{6,})([+-]\d{3,})',value)
    return .5*10.**(int(m[3])-len(m[2])) if m else 0.


def summarize(path,bolts,time,initial=None,displacements=None):
    from .solver import dat_real
    values={};control_roundoff={};node_roundoff={};active=None
    needed={int(n) for b in bolts for p in b['ports'].values() for n in p['weights']}
    for line in Path(path).read_text(encoding='utf-8',errors='replace').splitlines():
        low=line.strip().lower()
        if low.startswith('displacements ('):
            stamp=dat_real(low.rsplit('time',1)[1]);active=None
            if abs(stamp-time)<1e-7:
                if 'for set bolt_state ' in low:active='bolt'
                elif 'for set nall ' in low:active='physical'
            continue
        if low and low[0].isalpha():active=None
        if active:
            parts=line.split()
            if len(parts)==4:
                n=int(parts[0])
                if active=='bolt':
                    values[n]=[dat_real(v) for v in parts[1:]];control_roundoff[n]=[native_roundoff(v) for v in parts[1:]]
                elif n in needed:node_roundoff[n]=[native_roundoff(v) for v in parts[1:]]
    records=[];original={b['name']:b for b in initial or []}
    for b in bolts:
        if not all(n in values for n in (b['stretch_node'],b['adjustment_node'])):raise RuntimeError('missing bolt control displacement output')
        elongation=values[b['stretch_node']][0];q=values[b['adjustment_node']][0];force=b['stiffness_n_mm']*elongation
        if not np.all(np.isfinite([q,elongation,force])):raise RuntimeError('non-finite bolt state')
        locked=b['name'] in original
        error=abs(q-original[b['name']]['adjustment_mm']) if locked else abs(force-b['preload_n'])/b['preload_n']
        if error>(max(1e-9,abs(q)*1e-7) if locked else 5e-4):raise RuntimeError('bolt adjustment was not locked or full preload was not reached')
        port_u={r:sum((v*np.array(displacements[int(n)]) for n,v in p['weights'].items()),np.zeros(3)) for r,p in b['ports'].items()}
        delta=port_u['slave']-port_u['master'];axis=np.array(b['axis']);axial=float(delta@axis)
        roundoff=control_roundoff[b['stretch_node']][0]+control_roundoff[b['adjustment_node']][0]
        roundoff+=sum(abs(v)*float(abs(axis)@np.array(node_roundoff.get(int(n),[0.,0.,0.]))) for p in b['ports'].values() for n,v in p['weights'].items())
        residual=abs(elongation-(axial+q));tolerance=max(1e-9,abs(elongation)*1e-6)
        if residual>tolerance+roundoff:raise RuntimeError('bolt kinematic equation is inconsistent beyond native output roundoff')
        transverse=float(np.linalg.norm(delta-axial*axis))
        records.append({'name':b['name'],'force_n':force,'adjustment_mm':q,'elastic_extension_mm':elongation,
                        'attachment_extension_mm':axial,'utilization':max(force,0.)/b['allowable_tension_n'],
                        'locked':locked,'lock_error_mm':error if locked else None,'axis_screen_passed':transverse/b['span_mm']<=.01 and force>=0,
                        'kinematic_residual_mm':residual,'output_roundoff_bound_mm':roundoff,'base_kinematic_tolerance_mm':tolerance,
                        'meaning':'Equivalent fixed-axis axial bolt, force-controlled tightening then locked adjustment. Shear, bearing, threads, torque conversion and preload scatter are not assessed.'})
    return records
