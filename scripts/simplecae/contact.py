"""Explicit planar penalty/Coulomb contact; no linear capacity extrapolation."""
from pathlib import Path
import numpy as np
from .case import keys,number

# CalculiX C3D10 S1..S4 corner numbering. Mesh connectivity is already CCX ordered.
FACES=((0,1,2),(0,3,1),(1,3,2),(2,3,0))
# Fixed native stress readout resolution, shared by sign/Coulomb and zero
# convergence checks. It is not a task allowable and never clips output.
STRESS_RESOLUTION_MPA=1e-7


class ContactValidityError(RuntimeError):
    """A rejected native contact field, retaining its located raw evidence."""
    def __init__(self,message,diagnostic):
        super().__init__(message)
        self.diagnostic=diagnostic


def enabled(case):
    return any(c['type'] in ('frictionless_contact','frictional_contact') for c in case.get('connections',[]))


def stage_names(case):
    if case.get('bolts'):return ['preload','locked','service']
    return ['preload','service'] if case.get('gravity') or any(not l.get('scalable',True) for l in case.get('loads',[])) else ['service']


def validate_control(case):
    control=case.get('contact_control',{})
    keys(control,['initial_increment','minimum_increment','maximum_increment','max_increments',
                  'service_initial_increment','service_maximum_increment',
                  'contact_change_relative_tolerance'],[],'contact_control')
    initial=number(control.get('initial_increment',.1),'initial increment',True)
    minimum=number(control.get('minimum_increment',1e-6),'minimum increment',True)
    maximum=number(control.get('maximum_increment',.2),'maximum increment',True)
    if not minimum<=initial<=maximum<=1:raise ValueError('contact increments require 0 < minimum <= initial <= maximum <= 1')
    service_initial=number(control.get('service_initial_increment',initial),'service initial increment',True)
    service_maximum=number(control.get('service_maximum_increment',maximum),'service maximum increment',True)
    if not minimum<=service_initial<=service_maximum<=1:
        raise ValueError('service contact increments require minimum <= initial <= maximum <= 1')
    count=control.get('max_increments',200)
    if type(count) is not int or not 1<=count<=10000:raise ValueError('contact max_increments must be 1..10000')
    change=number(control.get('contact_change_relative_tolerance',0.),'contact change tolerance')
    if not 0<=change<=.001:raise ValueError('contact change relative tolerance must be 0..0.001; zero requires unchanged contact count')
    if 'contact_control' in case and not enabled(case):raise ValueError('contact_control requires planar contact')
    if enabled(case) and case.get('buckling',{}).get('enabled'):raise ValueError('contact buckling is not qualified')


def surface_index(tets):
    index={}
    for element,nodes in tets.items():
        for side,indices in enumerate(FACES,1):
            key=tuple(sorted(nodes[i] for i in indices))
            index.setdefault(key,[]).append((element,side))
    return index


def compile_contact(spec,patch,coords,tets,index,*,bodies=None,body_data=None):
    """Check complete planar footprints and outward normals without moving CAD."""
    from .assembly import overlay_samples
    master,slave=patch['master'],patch['slave'];normal=np.array(spec['normal'])
    surfaces={};tol=spec.get('position_tolerance_mm',1e-4)
    for role,sign in (('master',1),('slave',-1)):
        surfaces[role]=[]
        for tri in patch[role]['triangles']:
            owners=index.get(tuple(sorted(tri[:3])),[])
            if len(owners)!=1:raise ValueError('contact patch must contain external C3D10 faces')
            element,side=owners[0];nodes=tets[element]
            p=np.array([coords[nodes[i]] for i in FACES[side-1]])
            n=np.cross(p[1]-p[0],p[2]-p[0]);n/=np.linalg.norm(n)
            if n@(p.mean(axis=0)-np.mean([coords[n] for n in nodes[:4]],axis=0))<0:n=-n
            if n@normal*sign<1-1e-8:raise ValueError('contact normal must point outward from master toward the opposing slave')
            surfaces[role].append([element,side])
    gap=float((slave['center']-master['center'])@normal)
    geometric_tolerance=min(tol,max(np.linalg.norm(np.ptp(slave['points'],axis=0)),1.)*1e-8)
    if gap < -geometric_tolerance:raise ValueError('initial contact penetration is unsupported; repair the actual geometry')
    declared=spec.get('initial_gap_mm',0.)
    if abs(gap-declared)>geometric_tolerance:raise ValueError('contact geometric gap disagrees with initial_gap_mm; no automatic adjustment')
    # Translate a copy only for footprint integration; solver geometry stays exact.
    projected=dict(coords)
    for n in slave['nodes']:projected[n]=coords[n]-gap*normal
    projected_slave=dict(slave,points=slave['points']-gap*normal,center=slave['center']-gap*normal)
    area=0.;samples=0;gap_samples=[];coverage=None
    if spec.get('footprint','matching')=='slave_within_master':
        from .contact_footprint import cad_coverage,contained_samples
        coverage=cad_coverage(spec,bodies,body_data,normal,gap)
        stream=contained_samples(master,projected_slave,projected,spec.get('max_quadrature_points',30000),tol)
    else:stream=overlay_samples(master,projected_slave,projected,spec.get('max_quadrature_points',30000))
    for sample in stream:
        area+=sample[-2];samples+=1
        sn,sw,mn,mw,_,_,_=sample
        gap_samples.append({'slave_nodes':sn,'slave_weights':sw.tolist(),'master_nodes':mn,'master_weights':mw.tolist(),
                            'slave_face':list(index[tuple(sorted(sn[:3]))][0])})
    return {'name':spec['name'],'type':spec['type'],'surfaces':surfaces,
            'normal':normal.tolist(),'initial_gap_mm':gap,'area_mm2':area,'footprint_quadrature_points':samples,
            'footprint':spec.get('footprint','matching'),'cad_coverage':coverage,
            'normal_stiffness_n_mm3':spec['normal_stiffness_n_mm3'],'gap_samples':gap_samples,
            **{k:spec[k] for k in ('friction_coefficient','tangential_stiffness_n_mm3','max_tangential_displacement_mm') if k in spec},
            'footprint_extent_mm':float(np.linalg.norm(np.ptp(slave['points'],axis=0))),
            'meaning':'CalculiX face-to-face compression-only penalty contact; fixed initial footprint, small response, explicit friction law if supplied, no coordinate adjustment.'}


def deck(contacts):
    lines=[]
    for i,c in enumerate(contacts):
        for role,code in (('master','CM'),('slave','CS')):
            lines+=[f'*SURFACE,NAME={code}{i},TYPE=ELEMENT']+[f'{e},S{s}' for e,s in c['surfaces'][role]]
        lines += [f'*SURFACE INTERACTION,NAME=CI{i}','*SURFACE BEHAVIOR,PRESSURE-OVERCLOSURE=LINEAR',
                  f"{c['normal_stiffness_n_mm3']:.12e}"]
        if c['type']=='frictional_contact':lines+=['*FRICTION',f"{c['friction_coefficient']:.12e},{c['tangential_stiffness_n_mm3']:.12e}"]
        lines += [f'*CONTACT PAIR,INTERACTION=CI{i},TYPE=SURFACE TO SURFACE',f'CS{i},CM{i}']
    return lines


def steps(case,forces,meta):
    control=case.get('contact_control',{});fixed={int(n):np.array(v) for n,v in meta.get('fixed_nodal_forces',{}).items()}
    stages=[(name,forces if name=='service' else fixed) for name in stage_names(case)]
    bolts=meta['connection_data'].get('bolts',[])
    lines=[]
    for name,loads in stages:
        initial=control.get('initial_increment',.1);maximum=control.get('maximum_increment',.2)
        if name=='locked':
            # No load ramp occurs here: retain fixed loads and freeze the
            # converged adjustment. Verify this equilibrium in one full step;
            # CCX may still cut back if necessary. Do not skip the solve/output.
            initial=maximum=1.
        if name=='service':
            initial=control.get('service_initial_increment',initial)
            maximum=control.get('service_maximum_increment',maximum)
        lines += [f'** {name}: fixed loads retained; service uses actual full nodal loads',
                  f"*STEP,NLGEOM,INC={control.get('max_increments',200)}",
                  # CCX otherwise accepts up to 0.1% change in active contact
                  # count. A few last-update opening springs can then retain
                  # negative p=-kn*clearance. Do not clip or accept that output.
                  '*CONTROLS,PARAMETERS=CONTACT',
                  f"{control.get('contact_change_relative_tolerance',0.):.12e},0.1,100,60",
                  '*STATIC,SOLVER=SPOOLES',
                  f"{initial:.12e},1.,{control.get('minimum_increment',1e-6):.12e},{maximum:.12e}",'*CLOAD,OP=NEW']
        lines += [f'{n},{axis+1},{float(value):.12e}' for n,v in sorted(loads.items()) for axis,value in enumerate(v) if abs(value)>1e-14]
        if name=='preload':lines += [f"{b['adjustment_node']},1,{b['preload_n']:.12e}" for b in bolts]
        if name=='locked':lines += ['*BOUNDARY,FIXED']+[f"{b['adjustment_node']},1,1" for b in bolts]
        if name=='service' and meta.get('service_boundary'):
            lines+=['*BOUNDARY']+[f"{key.split(':')[0]},{key.split(':')[1]},{key.split(':')[1]},{value:.12e}" for key,value in meta['service_boundary'].items()]
        if bolts:lines+=['*NODE PRINT,NSET=BOLT_STATE,FREQUENCY=999999','U']
        lines += ['*CONTACT PRINT,FREQUENCY=999999','CDIS,CSTR','*NODE PRINT,NSET=NALL,FREQUENCY=999999','U',
                  '*NODE PRINT,NSET=FIXED,FREQUENCY=999999','RF','*EL PRINT,ELSET=EALL,GLOBAL=YES,FREQUENCY=999999','S,E',
                  '*NODE FILE,FREQUENCY=999999','U','*EL FILE,GLOBAL=YES,FREQUENCY=999999','S,E','*END STEP']
    return lines


def completed_steps(path,expected):
    """A completed increment is insufficient: every requested step must reach time 1."""
    last={}
    for line in Path(path).read_text().splitlines():
        parts=line.split()
        if len(parts)!=7:continue
        try:
            step=int(parts[0]);increment=int(parts[1]);int(parts[2]);int(parts[3]);time=float(parts[5].replace('D','E'))
        except ValueError:continue
        last[step]={'increment':increment,'step_time':time}
    if set(last)!=set(range(1,expected+1)) or any(abs(s['step_time']-1)>1e-7 for s in last.values()):
        raise RuntimeError('contact solve did not reach the full load in every requested step')
    return last


def summarize(path,contacts,time=None,*,displacements=None):
    from .solver import dat_real
    tables={'gap':{},'pressure':{}};section=None;selected_time=None
    for line in Path(path).read_text(errors='replace').splitlines():
        low=line.strip().lower()
        if low.startswith(('relative contact displacement (','contact stress (')):
            section='gap' if low.startswith('relative') else 'pressure'
            stamp=float(low.rsplit('time',1)[1].replace('d','e'))
            if time is not None and abs(stamp-time)>1e-7:section=None
            elif section:tables[section]={};selected_time=stamp
            continue
        if low and low[0].isalpha():section=None
        if not section:continue
        parts=line.split()
        if len(parts)!=5:continue
        values=[dat_real(p) for p in parts]
        if not np.all(np.isfinite(values)):raise RuntimeError('non-finite contact output')
        tables[section].setdefault((int(values[0]),int(values[1])),[]).append(values[2:])
    answer=[]
    for c in contacts:
        material_gaps=[];material_slips=[];face_gaps={}
        if displacements is not None:
            normal=np.array(c['normal'])
            for sample in c['gap_samples']:
                delta=np.array(sample['slave_weights'])@np.array([displacements[int(n)] for n in sample['slave_nodes']])-np.array(sample['master_weights'])@np.array([displacements[int(n)] for n in sample['master_nodes']])
                material_gaps.append(c['initial_gap_mm']+float(normal@delta))
                if 'slave_face' in sample:face_gaps.setdefault(tuple(sample['slave_face']),[]).append(material_gaps[-1])
                material_slips.append(float(np.linalg.norm(delta-(normal@delta)*normal)))
        faces={tuple(f) for f in c['surfaces']['slave']}
        for face in faces:
            if len(tables['gap'].get(face,[]))!=len(tables['pressure'].get(face,[])):
                raise RuntimeError('incomplete paired contact displacement/stress output')
            if face in face_gaps and not tables['pressure'].get(face) and min(face_gaps[face])<=1e-8:
                raise RuntimeError('missing contact output on a slave face without positive material-opening evidence')
        gaps=[v[0] for f,vs in tables['gap'].items() if f in faces for v in vs]
        stress_values=[v for f,vs in tables['pressure'].items() if f in faces for v in vs]
        gap_values=[v for f,vs in tables['gap'].items() if f in faces for v in vs]
        pressures=[v[0] for v in stress_values]
        if not gaps or not pressures:
            # Fully open patches have no generated contact elements in CCX.
            # Require positive actual material separation across the complete
            # segmented footprint; missing output alone never implies opening.
            if material_gaps and min(material_gaps)>1e-8:
                opened={'name':c['name'],'available':True,'output_coverage_verified':set(face_gaps)==faces,'minimum_gap_mm':min(material_gaps),'maximum_gap_mm':max(material_gaps),
                               'peak_pressure_mpa':0.,'minimum_pressure_mpa':0.,'contact_output_samples':0,
                               'meaning':'No native active contact elements; positive actual material separation checked at all segmented footprint quadrature points. Compression-only contact carries no pressure or friction when open.'}
                if c.get('type')=='frictional_contact':
                    opened.update(peak_tangential_displacement_mm=max(material_slips),peak_shear_mpa=0.,coulomb_bound_passed=True,sliding_sample_count=0,
                                  small_sliding_screen_passed=bool(max(material_slips)/c['footprint_extent_mm']<=.01))
                answer.append(opened);continue
            answer.append({'name':c['name'],'available':False,'reason':'No contact integration output; inspect material gap probes and stability.'});continue
        if min(pressures)<-STRESS_RESOLUTION_MPA:
            offending=[]
            for face,values in tables['pressure'].items():
                if face not in faces:continue
                for i,value in enumerate(values):
                    if value[0]>=-STRESS_RESOLUTION_MPA:continue
                    gap=tables['gap'][face][i][0]
                    item={'element_id':face[0],'face':face[1],'sample_index_on_face':i,
                          'pressure_mpa':value[0],'native_clearance_mm':gap,
                          'shear_components_mpa':value[1:]}
                    if 'normal_stiffness_n_mm3' in c:
                        item['nominal_linear_law_residual_mpa']=value[0]+c['normal_stiffness_n_mm3']*gap
                    offending.append(item)
            diagnostic={'contact':c['name'],'output_time':selected_time,'minimum_pressure_mpa':min(pressures),
                        'rejection_threshold_mpa':-STRESS_RESOLUTION_MPA,'offending_samples':offending,
                        'meaning':'Unmodified rejected native values. Positive native clearance means opening in the CCX face-to-face implementation. No stress clipping or verdict promotion.'}
            peak=min(offending,key=lambda p:p['pressure_mpa'])
            raise ContactValidityError('compression-only contact unexpectedly carries tensile pressure; '
                f"contact {c['name']!r}, minimum {peak['pressure_mpa']:.8g} MPa at element {peak['element_id']} "
                f"face {peak['face']}; {len(offending)} samples below unchanged threshold",diagnostic)
        record={'name':c['name'],'available':True,'output_coverage_verified':set(face_gaps)==faces,'minimum_gap_mm':min(gaps),'maximum_gap_mm':max(gaps),
                       'peak_pressure_mpa':max(pressures),'minimum_pressure_mpa':min(pressures),
                       'contact_output_samples':len(pressures),'meaning':'Native contact integration samples, not an area fraction or independently calibrated contact allowable.'}
        if c.get('type')=='frictional_contact':
            if not material_slips:raise RuntimeError('friction motion assessment requires actual material displacement fields')
            shear=np.linalg.norm(np.array(stress_values)[:,1:],axis=1);native_slip=np.linalg.norm(np.array(gap_values)[:,1:],axis=1)
            bound=c['friction_coefficient']*np.maximum(pressures,0.)
            record.update(peak_tangential_displacement_mm=max(material_slips),peak_native_tangential_displacement_mm=float(max(native_slip)),peak_shear_mpa=float(max(shear)),
                          coulomb_bound_passed=bool(np.all(shear<=bound*(1+5e-4)+STRESS_RESOLUTION_MPA)),
                          sliding_sample_count=int(np.sum((bound>1e-7)&(shear>=bound*(1-1e-4)))),
                          small_sliding_screen_passed=bool(max(material_slips)/c['footprint_extent_mm']<=.01),
                          tangential_displacement_meaning='Actual relative material-point motion on the initial segmented footprint, including elastic compliance; not accumulated irreversible slip or an area fraction. Native CDIS tangents are retained separately and do not define net material motion.')
        answer.append(record)
    return answer
