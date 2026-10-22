"""Native assembly frame/inertial handoff, independent of package JSON units.

The current SDK MJCF exporter supplies mesh assets and its rigid-group graph.
Reconstruct frames from the live evaluated CAD objects, never guess a scale
correction from suspicious serialized numbers. Preserve the upstream export.
"""
from pathlib import Path
from types import SimpleNamespace
import json
import math
import xml.etree.ElementTree as ET
import numpy as np
from . import HandoffError, _write, _hash, _notebook_provenance


def _matrix(p):return np.array([[*v,p.origin[i]] for i,v in enumerate(zip(p.x_axis,p.y_axis,p.z_axis))]+[[0,0,0,1]],float)


def _fmt(values):return ' '.join(format(float(v),'.15g') for v in values)


def _joint_alignment(parts,constraint):
    a,b=constraint.connector_a,constraint.connector_b
    ta=_matrix(parts[a.component_id].placement)@_matrix(parts[a.component_id].item.get_connector(a.connector_id).placement)
    tb=_matrix(parts[b.component_id].placement)@_matrix(parts[b.component_id].item.get_connector(b.connector_id).placement)
    offset=ta[:3,3]-tb[:3,3]
    error=float(np.linalg.norm(offset))
    transverse=float(np.linalg.norm(offset-np.dot(offset,ta[:3,2])*ta[:3,2]))
    angle=math.degrees(math.acos(float(np.clip(abs(np.dot(ta[:3,2],tb[:3,2])),-1,1))))
    if angle>.5 or (error if constraint.constraint_kind=='revolute' else transverse)>.1:
        raise HandoffError(f'{constraint.constraint_id}: native connector alignment failed ({error:g} mm, transverse {transverse:g} mm / {angle:g} deg)')
    return ta,error,transverse,angle


def _attributes(t):
    # Native CAD SDK quaternion conversion operates on evaluated millimetres.
    from simplecadapi.product.placement import Placement
    from simplecadapi.exporter.mjcf import _matrix_to_quat
    p=Placement(tuple(t[:3,3]),tuple(t[:3,0]),tuple(t[:3,1]),tuple(t[:3,2]))
    return {'pos':_fmt(t[:3,3]*.001),'quat':_fmt(_matrix_to_quat(p))}


def export_robot_for_cae(run,out_dir,*,materials):
    import simplecadapi as scad
    from simplecadapi.product.assembly import Assembly
    from simplecadapi.product.part import Part
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    product=run.product
    if not isinstance(product,Assembly) or any(not isinstance(c.item,Part) for c in product.components):
        raise HandoffError('Robot handoff currently requires a flat native Assembly of leaf Parts; flatten nested occurrences explicitly in CAD.')
    if any(c.constraint_kind not in ('fixed','revolute','prismatic') for c in product.constraints):
        raise HandoffError('Robot handoff supports fixed/revolute/prismatic trees only; coupled or closed-loop mechanisms need a dedicated model.')
    parts={c.component_id:c for c in product.components}
    alignments={c.constraint_id:_joint_alignment(parts,c) for c in product.constraints if c.constraint_kind in ('revolute','prismatic')}
    if set(materials)!=set(parts):raise HandoffError('materials must give each component a sourced density_kg_m3; CAD labels/default density are insufficient')
    for name,m in materials.items():
        if (not isinstance(m,dict) or not m.get('source') or isinstance(m.get('density_kg_m3'),bool)
                or not isinstance(m.get('density_kg_m3'),(int,float)) or not math.isfinite(m['density_kg_m3']) or m['density_kg_m3']<=0):
            raise HandoffError(f'{name}: supply positive density_kg_m3 and its source')
    out=Path(out_dir).resolve()
    if out.exists():raise HandoffError('Robot handoff output must be fresh')
    out.mkdir(parents=True);raw=out/'upstream';raw.mkdir()
    captured=scad.capture(run,out/'source.scadpkg')
    # Explicit fallback is only used by the preserved upstream diagnostic file.
    # All delivered inertials below use the separately sourced per-part values.
    export=scad.exporter.export_product_package_to_mjcf(captured.package,raw/'robot.xml',default_density_kg_m3=1.)
    mapping=json.loads(export.mapping_path.read_text(encoding='utf-8'))
    if export.equality_count or export.closure_count:raise HandoffError('Closed-loop MJCF handoff is unsupported; no constraints were removed')
    groups={g['group_id']:g for g in mapping['groups']}
    prefix='node/'+product.assembly_id+'/'
    world={prefix+n:_matrix(c.placement) for n,c in parts.items()}
    root_id='node/'+product.assembly_id
    world[root_id]=np.eye(4)
    frames={gid:(np.eye(4) if g['grounded'] else world[g['representative']]) for gid,g in groups.items()}
    constraints={c.constraint_id:c for c in product.constraints}
    tree=ET.parse(raw/'robot.xml');root=tree.getroot();world_xml=root.find('worldbody')
    body_nodes={gid:(world_xml if g['grounded'] else root.find(f".//body[@name='{g['body_name']}']")) for gid,g in groups.items()}
    evidence=[]
    for gid,g in groups.items():
        body=body_nodes[gid];frame=frames[gid]
        if body is None:raise HandoffError('Upstream MJCF group/body mapping is incomplete')
        if not g['grounded']:
            body.attrib.update(_attributes(np.linalg.inv(frames[g['parent_group']])@frame))
            record=next(x for x in mapping['tree_joints'] if x['group']==gid)
            cid=record['joint_id'].removeprefix('joint/'+product.assembly_id+'/')
            constraint=constraints[cid];a=constraint.connector_a;b=constraint.connector_b
            if prefix+b.component_id not in g['members']:
                raise HandoffError('Robot tree is reversed relative to connector_a -> connector_b; orient this constraint in native CAD before handoff')
            ta,error,transverse,angle=alignments[cid]
            local=np.linalg.inv(frame)@ta
            j=body.find('joint');j.set('pos',_fmt(local[:3,3]*.001));j.set('axis',_fmt(local[:3,2]))
            j.attrib.pop('range',None);j.attrib.pop('limited',None)
            limit=constraint.angle_limit if constraint.constraint_kind=='revolute' else constraint.distance_limit
            if limit is not None:
                scale=math.pi/180 if constraint.constraint_kind=='revolute' else .001
                reference=(constraint.drive_angle_degrees if constraint.constraint_kind=='revolute' else constraint.drive_distance) or 0.
                j.set('range',_fmt([(limit.lower_value-reference)*scale,(limit.upper_value-reference)*scale]));j.set('limited','true')
            evidence.append({'constraint':cid,'joint_name':j.get('name'),'origin_world_mm':ta[:3,3].tolist(),
                             'axis_world':ta[:3,2].tolist(),'connector_position_error_mm':error,'connector_transverse_error_mm':transverse,'connector_axis_error_deg':angle,
                             'cad_reference_drive':constraint.drive_angle_degrees if constraint.constraint_kind=='revolute' else constraint.drive_distance})
        masses=[];centers=[];tensors=[]
        for node in g['members']:
            if node==root_id:continue
            name=node.removeprefix(prefix);part=parts[name].item
            local=np.linalg.inv(frame)@world[node]
            geom=next((v for v in body.findall('geom') if v.get('name')==name),None)
            if geom is None:raise HandoffError('Upstream mesh occurrence does not identify native component '+name)
            geom.attrib.update(_attributes(local));geom.set('density',str(materials[name]['density_kg_m3']))
            props=GProp_GProps();BRepGProp.VolumeProperties_s(part.body.wrapped,props)
            density=materials[name]['density_kg_m3'];mass=props.Mass()*1e-9*density
            center=props.CentreOfMass();center=local[:3,:3]@np.array([center.X(),center.Y(),center.Z()])+local[:3,3]
            tensor=props.MatrixOfInertia();tensor=np.array([[tensor.Value(i+1,j+1) for j in range(3)] for i in range(3)])*density*1e-15
            tensor=local[:3,:3]@tensor@local[:3,:3].T
            masses.append(mass);centers.append(center*.001);tensors.append(tensor)
        if masses:
            mass=sum(masses);center=sum(m*c for m,c in zip(masses,centers))/mass
            inertia=sum(t+m*(np.dot(c-center,c-center)*np.eye(3)-np.outer(c-center,c-center)) for m,c,t in zip(masses,centers,tensors))
            ET.SubElement(body,'inertial',mass=str(mass),pos=_fmt(center),fullinertia=_fmt([inertia[0,0],inertia[1,1],inertia[2,2],inertia[0,1],inertia[0,2],inertia[1,2]]))
        # Sites are display-only but must not retain corrupt serialized frames.
        for site in list(body.findall('site')):body.remove(site)
    for mesh in root.findall('asset/mesh'):
        mesh.set('file',str((raw/mesh.get('file')).resolve()))
    destination=out/'robot.xml';ET.indent(tree);tree.write(destination,encoding='utf-8',xml_declaration=True)
    report={'status':'exported','mjcf':str(destination),'mjcf_sha256':_hash(destination),'source_package_sha256':_hash(out/'source.scadpkg'),
            'provenance':_notebook_provenance(run,None),'materials':materials,'native_joint_frames':evidence,
            'upstream_export':export.to_dict(),'frame_source':'live evaluated native CAD placements and connectors',
            'whole_product_pass_available':False,
            'limitations':['Flat scalar-joint tree only; q=0 is the evaluated CAD pose.',
                           'Inertials use exact native volume properties and explicitly sourced homogeneous density, not CAD material labels.',
                           'Upstream MJCF is retained for diagnostics. Delivered frames and inertials are regenerated from native CAD; display sites are omitted.']}
    _write(out/'handoff.json',report);return report
