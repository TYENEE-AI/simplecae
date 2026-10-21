"""Bounded finite-pad wrench resistance with an inner friction pyramid.

This tests a declared wrench, not universal force closure or real pressure.
All input positions/moments use SI; LP rows/forces are normalized internally.
"""
import numpy as np
from scipy.optimize import linprog
from .case import keys,number,vector

def finite_pad_wrench(pads,external_fixed,external_variable=None,*,reference_world_m=None,
                      declared_pad_fixed=None,declared_pad_variable=None):
    if not isinstance(pads,list) or len(pads)<2:raise ValueError('finite-pad wrench needs at least two explicit pad models')
    checked=[];names=[]
    for i,p in enumerate(pads):
        keys(p,['name','center_world_m','inward_normal_world','tangent_u_world','tangent_v_world','half_extents_m','normal_force_n','friction_coefficient'],
             ['center_world_m','inward_normal_world','tangent_u_world','tangent_v_world','half_extents_m','normal_force_n','friction_coefficient'],'pad')
        center=np.array(vector(p['center_world_m'],'pad center'))
        basis=np.array([vector(p[k],'pad axis') for k in ('inward_normal_world','tangent_u_world','tangent_v_world')])
        if not np.allclose(basis@basis.T,np.eye(3),rtol=0,atol=1e-8):raise ValueError('pad normal and tangent axes must form an orthonormal basis')
        size=p['half_extents_m']
        if not isinstance(size,list) or len(size)!=2:raise ValueError('pad half_extents_m must have two positive dimensions')
        half=np.array([number(v,'pad half extent',True) for v in size])
        normal=number(p['normal_force_n'],'pad normal force',True);mu=number(p['friction_coefficient'],'pad friction')
        if mu<0:raise ValueError('pad friction must be nonnegative')
        name=p.get('name',f'pad-{i+1}')
        if not isinstance(name,str) or not name:raise ValueError('pad name must be nonempty')
        names.append(name);checked.append((center,basis,half,normal,mu,name))
    if len(set(names))!=len(names):raise ValueError('pad names must be unique')
    def wrench(value,label):
        if not isinstance(value,(list,np.ndarray)) or len(value)!=6:raise ValueError(label+' must have six SI force/moment components')
        return np.array([number(v,label) for v in value])
    fixed=wrench(external_fixed,'fixed external wrench');variable=wrench(external_variable,'variable external wrench') if external_variable is not None else None
    reference=np.mean([p[0] for p in checked],axis=0) if reference_world_m is None else np.array(vector(reference_world_m,'wrench reference'))
    contacts=[]
    for pad_index,(center,basis,half,normal,mu,name) in enumerate(checked):
        for su in (-1,1):
            for sv in (-1,1):contacts.append((center+su*half[0]*basis[1]+sv*half[1]*basis[2],basis,pad_index,mu))
    length=max(float(np.max(np.linalg.norm(np.array([p[0] for p in contacts])-reference,axis=1))),1e-12)
    force_scale=max(sum(p[3] for p in checked),np.linalg.norm(fixed[:3]),np.linalg.norm(fixed[3:])/length,
                    np.linalg.norm(variable[:3]) if variable is not None else 0,
                    np.linalg.norm(variable[3:])/length if variable is not None else 0,1e-12)
    unit_scale=np.array([force_scale]*3+[force_scale*length]*3)
    matrix=np.zeros((6,3*len(contacts)));ineq=[]
    for i,(point,basis,pad,mu) in enumerate(contacts):
        matrix[:3,3*i:3*i+3]=basis.T
        matrix[3:,3*i:3*i+3]=np.column_stack([np.cross(point-reference,d)/length for d in basis])
        for su in (-1,1):
            for sv in (-1,1):
                row=np.zeros(3*len(contacts));row[3*i:3*i+3]=[-mu,su,sv];ineq.append(row)
    eq=[row for row in matrix];rhs=list(-fixed/unit_scale)
    if variable is not None:eq=[np.r_[row,v] for row,v in zip(eq,variable/unit_scale)]
    for pad_index,(_,_,_,normal,_,_) in enumerate(checked):
        row=np.zeros(3*len(contacts)+(variable is not None))
        for i,p in enumerate(contacts):
            if p[2]==pad_index:row[3*i]=1
        eq.append(row);rhs.append(normal/force_scale)
    if variable is not None and (declared_pad_fixed is None)!=(declared_pad_variable is None):
        raise ValueError('per-pad fixed and variable wrenches must be provided together')
    if variable is None and declared_pad_variable is not None:raise ValueError('per-pad variable wrenches require an external variable wrench')
    if declared_pad_fixed is not None:
        if len(declared_pad_fixed)!=len(pads) or (variable is not None and len(declared_pad_variable)!=len(pads)):
            raise ValueError('per-pad wrench lists must match pads')
        for pad_index,w in enumerate(declared_pad_fixed):
            f=wrench(w,'declared fixed pad wrench');v=wrench(declared_pad_variable[pad_index],'declared variable pad wrench') if variable is not None else None
            selected=matrix.copy()
            for i,contact in enumerate(contacts):
                if contact[2]!=pad_index:selected[:,3*i:3*i+3]=0
            for row,value,derivative in zip(selected,f/unit_scale,v/unit_scale if v is not None else [0]*6):
                eq.append(np.r_[row,-derivative] if variable is not None else row);rhs.append(value)
    a=np.asarray(eq);b=np.asarray(rhs);ineq=np.array(ineq)
    objective=np.zeros(a.shape[1]);bounds=[(0,None) if i%3==0 else (None,None) for i in range(3*len(contacts))]
    if variable is not None:
        objective[-1]=-1;bounds.append((0,None));ineq=np.c_[ineq,np.zeros(len(ineq))]
    solution=linprog(objective,A_ub=ineq,b_ub=np.zeros(len(ineq)),A_eq=a,b_eq=b,bounds=bounds,method='highs')
    base={'reference_world_m':reference.tolist(),'characteristic_length_m':length,
          'mode':'declared_per_pad_wrenches' if declared_pad_fixed is not None else 'total_workpiece_wrench',
          'friction_model':'inner pyramid |Ft_u|+|Ft_v|<=mu*Fn; Fn>=0; per-pad total normal force fixed',
          'scope':'Declared full rectangular pad corner contacts and bounded normal force; no contact pressure, partial contact, pad compliance or physical friction proof.'}
    if solution.status==3 and variable is not None:return dict(base,feasible=True,unbounded=True,payload_scale_limit=None)
    if solution.status==2:return dict(base,feasible=False,payload_scale_limit=None,solver_status=2)
    if not solution.success:raise RuntimeError(f'finite-pad LP numerical failure: {solution.status} {solution.message}')
    residual=float(np.linalg.norm(a@solution.x-b,np.inf));cone_error=float(max(np.max(ineq@solution.x),0))
    if residual>1e-7 or cone_error>1e-7:raise RuntimeError('finite-pad LP failed independent equilibrium/friction residual checks')
    components=solution.x[:3*len(contacts)].reshape(-1,3)*force_scale
    forces=np.array([basis.T@f for (_,basis,_,_),f in zip(contacts,components)])
    world_force=forces.sum(axis=0);world_moment=sum((np.cross(point-reference,f) for (point,_,_,_),f in zip(contacts,forces)),np.zeros(3))
    scale=float(solution.x[-1]) if variable is not None else None
    demand=fixed+(scale*variable if variable is not None else 0)
    force_res=float(np.linalg.norm(world_force+demand[:3])/force_scale)
    moment_res=float(np.linalg.norm(world_moment+demand[3:])/(force_scale*length))
    if max(force_res,moment_res)>1e-7:raise RuntimeError('finite-pad force/moment conservation failed')
    return dict(base,feasible=True,payload_scale_limit=scale,relative_force_residual=force_res,relative_moment_residual=moment_res,
        normalized_constraint_residual=residual,contact_forces=[{'pad':checked[p][5],'position_world_m':point.tolist(),
            'force_world_n':f.tolist(),'normal_force_n':float(comp[0]),'tangent_components_n':comp[1:].tolist()}
            for (point,_,p,_),f,comp in zip(contacts,forces,components)])
