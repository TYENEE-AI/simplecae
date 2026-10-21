import copy
import numpy as np
import pytest
from simplecae.materials import validate_material,engineering_compliance,local_stresses,strength_values,context
from simplecae.assessment import fixed_load_limit


def orthotropic():
    return {'name':'prescribed_directional','source':'Mathematical reference, not PLA/PETG or a material certificate',
        'elastic_model':'orthotropic','engineering_constants':{'e1_mpa':10000.,'e2_mpa':5000.,'e3_mpa':2000.,
        'nu12':0.,'nu13':0.,'nu23':0.,'g12_mpa':2000.,'g13_mpa':1000.,'g23_mpa':800.},
        'orientation':{'axis_1':[1,0,0],'axis_2':[0,1,0]},'failure_criterion':'max_stress',
        'strengths':{'tension_mpa':[50.,25.,10.],'compression_mpa':[30.,15.,8.],'shear_mpa':[15.,10.,8.]},
        'calibration':{'kind':'mathematical_reference','reference':'Prescribed independent directional limits',
                       'applicability':'Homogeneous mathematical model at small strain; no manufactured-part claim'}}


def test_invalid_energy_and_axes_rejected():
    m=orthotropic();m['engineering_constants']['nu12']=2.
    with pytest.raises(ValueError,match='positive elastic energy'):validate_material(m)
    m=orthotropic();m['orientation']['axis_2']=[1,0,0]
    with pytest.raises(ValueError,match='orthonormal'):validate_material(m)
    m=orthotropic();m['failure_criterion']='von_mises_yield'
    with pytest.raises(ValueError,match='orthotropic failure'):validate_material(m)


def test_reciprocity_and_isotropic_limit_compliance():
    e=200000.;n=.3;g=e/(2*(1+n));m=orthotropic()
    m['engineering_constants']={k:v for k,v in zip(m['engineering_constants'],[e,e,e,n,n,n,g,g,g])}
    s=engineering_compliance(m['engineering_constants'])
    assert np.allclose(s,s.T)
    assert np.allclose(s@np.array([100,0,0,0,0,0]),[100/e,-n*100/e,-n*100/e,0,0,0])
    assert s[3,3]*10==pytest.approx(10/g)


def test_rotated_uniaxial_stress_requires_material_axis_shear_check():
    m=orthotropic();q=2**-.5;m['orientation']={'axis_1':[q,q,0],'axis_2':[-q,q,0]}
    m['strengths']={'tension_mpa':[200,200,200],'compression_mpa':[200,200,200],'shear_mpa':[40,40,40]}
    assert np.allclose(local_stresses([[100,0,0,0,0,0]],m),[[50,50,0,-50,0,0]])
    ctx={'materials':{'M':m},'element_material':{'1':'M'},'safety_factor':1}
    values,components=strength_values([[100,0,0,0,0,0]],[(1,1)],ctx)
    assert values[0]==pytest.approx(1.25) and components[0]==3


def test_compression_strength_not_replaced_by_tension_strength():
    m=orthotropic();ctx={'materials':{'M':m},'element_material':{'1':'M'},'safety_factor':2}
    values,_=strength_values([[-20,0,0,0,0,0],[20,0,0,0,0,0]],[(1,1),(1,2)],ctx)
    assert values[0]==pytest.approx(20/15) and values[1]==pytest.approx(20/25)


def test_signed_fixed_preload_plus_payload_uses_directional_limits():
    m=orthotropic();m['strengths']['tension_mpa'][0]=40.;m['strengths']['compression_mpa'][0]=12.
    ctx={'materials':{'M':m},'element_material':{'1':'M'},'safety_factor':2}
    def fields(s,u):return {'stresses':{(1,1):np.array([s,0.,0.,0.,0.,0.])},'strains':{(1,1):np.zeros(6)},
                           'displacements':{1:np.array([u,0,0])},'_strength_context':ctx}
    factor,governing=fixed_load_limit(fields(14,.01),fields(-4,.001),None,.05)
    assert factor==pytest.approx(4/3) and governing=='strength'


def test_heterogeneous_strength_uses_each_element_material():
    strong=orthotropic();weak=copy.deepcopy(strong);weak['strengths']['tension_mpa'][0]=10.
    ctx={'materials':{'S':strong,'W':weak},'element_material':{'1':'S','2':'W'},'safety_factor':2}
    values,_=strength_values([[5,0,0,0,0,0],[8,0,0,0,0,0]],[(1,1),(2,1)],ctx)
    assert np.allclose(values,[.2,1.6])
    del weak['strengths'];values,_=strength_values([[5,0,0,0,0,0],[8,0,0,0,0,0]],[(1,1),(2,1)],ctx)
    assert values is None
