"""Calibrated material axes, positive elastic energy and explicit failure models."""
import numpy as np
from .case import keys,number,vector

CONSTANTS=('e1_mpa','e2_mpa','e3_mpa','nu12','nu13','nu23','g12_mpa','g13_mpa','g23_mpa')
COMPONENTS=('sigma_1','sigma_2','sigma_3','tau_12','tau_13','tau_23')


def primary_material(case):
    return case['material'] if 'material' in case else case['bodies'][0]['material']


def axes(material):
    orientation=material.get('orientation',{'axis_1':[1,0,0],'axis_2':[0,1,0]})
    a=np.asarray(orientation['axis_1'],float);b=np.asarray(orientation['axis_2'],float)
    return np.column_stack((a,b,np.cross(a,b)))


def engineering_compliance(constants):
    e1,e2,e3,n12,n13,n23,g12,g13,g23=[constants[k] for k in CONSTANTS]
    s=np.diag([1/e1,1/e2,1/e3,1/g12,1/g13,1/g23])
    s[0,1]=s[1,0]=-n12/e1;s[0,2]=s[2,0]=-n13/e1;s[1,2]=s[2,1]=-n23/e2
    return s


def validate_material(m,version='2.0'):
    advanced=version!='1.0'
    extra=['density_kg_m3','elastic_model','engineering_constants','orientation','strengths','calibration'] if advanced else []
    allowed=['name','youngs_modulus_mpa','poisson_ratio','yield_strength_mpa','source','failure_criterion']+extra
    keys(m,allowed,['name','source'],'material')
    for field in ('name','source'):
        if not isinstance(m[field],str) or not m[field].strip():raise ValueError(f'material.{field} must be nonempty')
    model=m.get('elastic_model','isotropic')
    if model not in ('isotropic','orthotropic'):raise ValueError('elastic_model must be isotropic or orthotropic')
    if model=='isotropic':
        keys(m,allowed,['youngs_modulus_mpa','poisson_ratio'],'isotropic material')
        number(m['youngs_modulus_mpa'],"Young's modulus",True)
        if not -1<number(m['poisson_ratio'],'Poisson ratio')<.5:raise ValueError('Poisson ratio must be between -1 and 0.5')
        if 'engineering_constants' in m:raise ValueError('isotropic material must not also declare orthotropic constants')
    else:
        if 'youngs_modulus_mpa' in m or 'poisson_ratio' in m or 'yield_strength_mpa' in m:
            raise ValueError('orthotropic material needs directional constants/allowables, not isotropic or nominal yield values')
        keys(m,allowed,['engineering_constants','orientation'],'orthotropic material')
        constants=m['engineering_constants'];keys(constants,CONSTANTS,CONSTANTS,'engineering_constants')
        for key,value in constants.items():number(value,key,key.startswith(('e','g')))
        s=engineering_compliance(constants)
        normalized=s/np.sqrt(np.outer(np.diag(s),np.diag(s)))
        if np.linalg.eigvalsh(normalized)[0]<=1e-10:
            raise ValueError('orthotropic compliance must have positive elastic energy; constants violate reciprocity/stability or are nearly singular')
    if 'orientation' in m:
        keys(m['orientation'],['axis_1','axis_2'],['axis_1','axis_2'],'material orientation')
        a=vector(m['orientation']['axis_1'],'axis_1');b=vector(m['orientation']['axis_2'],'axis_2')
        if not np.allclose([np.linalg.norm(a),np.linalg.norm(b),np.dot(a,b)],[1,1,0],rtol=0,atol=1e-8):
            raise ValueError('material axes must be orthonormal unit vectors; no implicit axis repair')
    failure=m.get('failure_criterion','not_specified')
    if failure not in ('not_specified','von_mises_yield','max_stress'):raise ValueError('unsupported failure criterion')
    if not advanced and failure=='max_stress':raise ValueError('max_stress requires case v2')
    if model=='orthotropic' and failure=='von_mises_yield':raise ValueError('von Mises yield is not a calibrated orthotropic failure criterion')
    if 'strengths' in m:
        keys(m['strengths'],['tension_mpa','compression_mpa','shear_mpa'],['tension_mpa','compression_mpa','shear_mpa'],'directional strengths')
        for key,values in m['strengths'].items():
            for v in vector(values,key):number(v,key,True)
        if failure!='max_stress':raise ValueError('directional strengths require explicit max_stress criterion')
    if m.get('yield_strength_mpa') is not None:number(m['yield_strength_mpa'],'yield strength',True)
    if 'density_kg_m3' in m:number(m['density_kg_m3'],'density_kg_m3',True)
    if 'calibration' in m:
        keys(m['calibration'],['kind','reference','applicability'],['kind','reference','applicability'],'calibration')
        if m['calibration']['kind'] not in ('coupon_tests','literature','mathematical_reference'):
            raise ValueError('calibration.kind must be coupon_tests, literature or mathematical_reference')
        for k in ('reference','applicability'):
            if not isinstance(m['calibration'][k],str) or not m['calibration'][k].strip():raise ValueError('calibration reference and applicability must be recorded')
    return m


def material_deck(material,name,element_set):
    lines=[f'*MATERIAL,NAME={name}']
    if material.get('elastic_model','isotropic')=='orthotropic':
        v=[material['engineering_constants'][k] for k in CONSTANTS]
        lines+=['*ELASTIC,TYPE=ENGINEERING CONSTANTS',','.join(f'{x:.12g}' for x in v[:8]),f'{v[8]:.12g}']
    else:lines+=['*ELASTIC',f"{material['youngs_modulus_mpa']:.12g},{material['poisson_ratio']:.12g}"]
    orientation=''
    if 'orientation' in material:
        r=axes(material);lines+=[f'*ORIENTATION,NAME=ORI_{name},SYSTEM=RECTANGULAR',','.join(f'{x:.12g}' for x in np.r_[r[:,0],r[:,1]])]
        orientation=f',ORIENTATION=ORI_{name}'
    lines+=[f'*SOLID SECTION,ELSET={element_set},MATERIAL={name}{orientation}']
    return lines


def local_stresses(stresses,material):
    stress=np.asarray(stresses,float).reshape(-1,6)
    tensors=np.zeros((len(stress),3,3))
    for i in range(3):tensors[:,i,i]=stress[:,i]
    for k,(i,j) in enumerate(((0,1),(0,2),(1,2)),3):tensors[:,i,j]=tensors[:,j,i]=stress[:,k]
    r=axes(material);local=np.einsum('ai,nab,bj->nij',r,tensors,r)
    return np.column_stack([local[:,0,0],local[:,1,1],local[:,2,2],local[:,0,1],local[:,0,2],local[:,1,2]])


def context(case,meta,tets):
    return {'materials':meta.get('materials',{'BODY':primary_material(case)}),
            'element_material':meta.get('element_material',{str(e):'BODY' for e in tets}),
            'safety_factor':case['criteria'].get('strength_safety_factor',case['criteria'].get('yield_safety_factor'))}


def strength_values(stresses,point_keys,ctx):
    """Dimensionless utilization per point, retaining signed normal criteria."""
    safety=ctx.get('safety_factor');materials=ctx['materials']
    if safety is None:return None,None
    stress=np.asarray(stresses,float);labels=np.array([ctx['element_material'][str(k[0])] for k in point_keys])
    values=np.zeros(len(stress));components=np.zeros(len(stress),int)
    for name,m in materials.items():
        mask=labels==name
        if not np.any(mask):continue
        failure=m.get('failure_criterion','not_specified')
        if failure=='von_mises_yield' and m.get('yield_strength_mpa'):
            s=stress[mask];vm=np.sqrt(.5*((s[:,0]-s[:,1])**2+(s[:,1]-s[:,2])**2+(s[:,2]-s[:,0])**2)+3*np.sum(s[:,3:]**2,axis=1))
            values[mask]=vm/(m['yield_strength_mpa']/safety);components[mask]=-1
        elif failure=='max_stress' and m.get('strengths'):
            s=local_stresses(stress[mask],m);limits=m['strengths']
            normals=np.where(s[:,:3]>=0,np.array(limits['tension_mpa']),np.array(limits['compression_mpa']))/safety
            ratios=np.c_[np.abs(s[:,:3])/normals,np.abs(s[:,3:])/(np.array(limits['shear_mpa'])/safety)]
            values[mask]=ratios.max(axis=1);components[mask]=ratios.argmax(axis=1)
        else:return None,None
    return values,components


def strength_summary(stresses,point_keys,ctx):
    values,components=strength_values(stresses,point_keys,ctx)
    if values is None:return {'strength_utilization':None,'strength_peak':None}
    i=int(np.argmax(values));key=point_keys[i];name=ctx['element_material'][str(key[0])];material=ctx['materials'][name]
    local=local_stresses(np.asarray(stresses)[i:i+1],material)[0]
    return {'strength_utilization':float(values[i]),'strength_peak':{'element':int(key[0]),'integration_point':int(key[1]),
        'material_id':name,'failure_criterion':material.get('failure_criterion'),
        'component':COMPONENTS[components[i]] if components[i]>=0 else 'von_mises',
        'material_axis_stress_mpa':local.tolist(),'utilization':float(values[i])}}
