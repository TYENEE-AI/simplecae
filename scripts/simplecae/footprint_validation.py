"""Native curved annular axial joint reference, independent of application CAD."""
from pathlib import Path
import math
from .case import write_json
from .api import analyze_case


def validate_footprints(out,ccx=None,timeout=300):
    from .geometry import session
    out=Path(out).resolve();out.mkdir(parents=True,exist_ok=False)
    with session() as g:
        a=g.model.occ.addCylinder(0,0,0,10,0,0,4)
        b=g.model.occ.addCylinder(-1,0,0,12,0,0,2)
        g.model.occ.cut([(3,a)],[(3,b)]);g.model.occ.synchronize();g.write(str(out/'annular-bar.step'))
    plane=lambda x:{'type':'plane','axis':'x','position_mm':x}
    material={'name':'mathematical-reference','source':'Prescribed elastic constants, not physical product evidence',
        'youngs_modulus_mpa':200000.,'poisson_ratio':0.,'yield_strength_mpa':200.,'failure_criterion':'von_mises_yield',
        'calibration':{'kind':'mathematical_reference','reference':'E=200000 MPa, nu=0, ring Ro=4 Ri=2, each length10 mm',
                       'applicability':'Analytic axial joint verification only'}}
    c={'schema_version':'assembly-1.0','bodies':[{'name':'fixed-ring','model':{'path':str(out/'annular-bar.step')},'material':material},
         {'name':'moving-ring','model':{'path':str(out/'annular-bar.step')},'material':material,'mesh_size_factor':.8,
          'placement':{'translation_mm':[10,0,0],'rpy_rad':[0,0,0]}}],
       'supports':[{'name':'root','body':'fixed-ring','selector':plane(0)},
                   {'name':'transverse-test-guide','body':'moving-ring','selector':plane(0),'dofs':[2,3]}],
       'loads':[{'name':'pull','body':'moving-ring','selector':plane(10),'total_force_n':[50.,0,0]}],
       'connections':[{'name':'annular-seat','type':'frictionless_contact','master':{'body':'fixed-ring','selector':plane(10)},
                       'slave':{'body':'moving-ring','selector':plane(0)},'normal':[1,0,0],
                       'footprint':'slave_within_master','normal_stiffness_n_mm3':100000.}],
       'bolts':[{'name':'axial-tie','master':{'body':'fixed-ring','selector':plane(0)},
                 'slave':{'body':'moving-ring','selector':plane(10)},'axis':[1,0,0],
                 'axial_stiffness_n_mm':10000.,'preload_n':200.,'allowable_tension_n':1000.,
                 'reference':'Prescribed kb=10000 N/mm, P0=200 N; guides are the analytic test fixture, not product supports.'}],
       'criteria':{'strength_safety_factor':2.,'max_displacement_mm':.1},'mesh':{'sizes_mm':[1.6,1.28,1.024]},
       'contact_control':{'initial_increment':1.,'maximum_increment':1.,'minimum_increment':1e-6,'max_increments':200},
       'conditions':{k:True for k in ('material_verified','dimensions_verified','supports_represent_actual_mounting','load_pattern_verified','self_weight_negligible','connection_parameters_verified')},
       'provenance':{'task_id':'annular-axial-joint-reference','revision':'1'}}
    for body,x in zip(c['bodies'],(10,0)):
        body['local_refinements']=[{'name':'contact-resolution','selector':plane(x),'size_factor':.2,'distance_mm':2.}]
    write_json(out/'case.json',c)
    r=analyze_case(out/'case.json',out/'analysis',ccx=ccx,timeout=timeout,preview=False,storage='full')
    area=math.pi*12;kc=1/(20/(200000*area)+1/(100000*area));fraction=10000/(10000+kc)
    reference={'bolt_force_n':200+fraction*50,'pressure_mpa':(200-(1-fraction)*50)/area,
               'formula':'A=pi*(4^2-2^2); kc=1/(20/(E*A)+1/(kn*A)); C=kb/(kb+kc); Fb=P0+C*P; p=(P0-(1-C)*P)/A',
               'relative_tolerance':.005}
    checks=[]
    def check(name,value):checks.append({'name':name,'passed':bool(value)})
    check('all three meshes solved',len(r['levels'])==3)
    check('not invalid',r['status']!='invalid')
    check('complete model verdict',r['status']=='pass_under_stated_model')
    for i,l in enumerate(r['levels']):
        result=l['results'];check(f'level{i+1} full stages',set(map(int,l['solver']['completed_load_steps']))=={1,2,3})
        check(f'level{i+1} axial force',abs(result['bolts'][0]['force_n']/reference['bolt_force_n']-1)<=.005)
        check(f'level{i+1} peak pressure',abs(result['contact'][0]['peak_pressure_mpa']/reference['pressure_mpa']-1)<=.005)
        check(f'level{i+1} force moment balance',max(result['force_balance_relative_error'],result['moment_balance_relative_error'])<=5e-4)
    check('no product capacity',not r['evaluation_signal']['whole_installation_rating_available'])
    summary={'passed':all(x['passed'] for x in checks),'checks':checks,'reference':reference,'analysis_status':r['status'],
             'scope':'Native curved annular port, nonmatching P2 meshes and locked axial bolt. Numerical reference only.'}
    write_json(out/'validation.json',summary);return summary
