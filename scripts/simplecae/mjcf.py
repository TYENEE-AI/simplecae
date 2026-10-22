"""Restricted MJCF tree to URDF handoff. No dynamics or guessed inertials.

Local body frames, one hinge/slide per body, explicit inertials and file meshes.
Closed loops, defaults, springs and free/ball joints require another model.
"""
from pathlib import Path
import json
import shutil
import xml.etree.ElementTree as XML
from defusedxml import ElementTree as SafeXML
import numpy as np
from scipy.spatial.transform import Rotation
from .case import sha256, write_json, vector, number


def _vec(text, count=3, default=None):
    values=[float(v) for v in text.split()] if text is not None else list(default or [0]*count)
    if len(values)!=count or not np.isfinite(values).all():raise ValueError('MJCF vector has invalid size or nonfinite values')
    return np.asarray(values)


def _frame(element):
    if any(k in element.attrib for k in ('euler','axisangle','xyaxes','zaxis')):
        raise ValueError('MJCF handoff supports explicit pos/quat frames; export local quaternion frames first')
    t=np.eye(4);t[:3,3]=_vec(element.get('pos'))
    q=_vec(element.get('quat'),4,[1,0,0,0])
    if np.linalg.norm(q)==0:raise ValueError('MJCF quaternion is zero')
    t[:3,:3]=Rotation.from_quat(q[[1,2,3,0]]).as_matrix()
    return t


def _text(values):return ' '.join(format(float(v),'.15g') for v in values)


def _origin(parent,t):
    XML.SubElement(parent,'origin',xyz=_text(t[:3,3]),rpy=_text(Rotation.from_matrix(t[:3,:3]).as_euler('xyz')))


def convert(path,out,*,inertials=None,reference=None):
    path=Path(path).resolve();out=Path(out).resolve()
    if out.exists():raise ValueError('MJCF handoff output must be fresh')
    root=SafeXML.parse(path).getroot()
    if root.tag!='mujoco':raise ValueError('Expected a mujoco MJCF document')
    unsupported={'include','default','equality','tendon','actuator','flex','flexcomp','freejoint','plugin','composite'}
    for e in root.iter():
        if e.tag in unsupported and (len(e) or e.attrib):raise ValueError(f'Unsupported MJCF {e.tag}; do not discard constraints/actuation. Export an explicit fixed-base scalar-joint tree.')
        if 'class' in e.attrib or 'childclass' in e.attrib:raise ValueError('Resolve MJCF defaults/classes before handoff')
    # This is a deliberately small translator. Unknown semantics must not turn
    # into a plausible-looking but different robot without an actionable error.
    attributes={
        'mujoco':{'model'}, 'compiler':{'angle','coordinate','meshdir'},
        'option':{'gravity'}, 'asset':set(), 'mesh':{'name','file','scale'},
        'worldbody':set(), 'body':{'name','pos','quat','mocap','gravcomp'},
        'joint':{'name','type','pos','axis','limited','range'},
        'inertial':{'mass','pos','quat','diaginertia','fullinertia'},
        'geom':{'name','type','mesh','pos','quat','density','mass','contype','conaffinity','rgba','group'},
    }
    children={'mujoco':{'compiler','option','asset','worldbody'},'asset':{'mesh'},
              'worldbody':{'body','geom','inertial'},'body':{'body','geom','joint','inertial'}}
    for element in root.iter():
        if element.tag not in attributes or set(element.attrib)-attributes[element.tag]:
            raise ValueError(f'Unsupported MJCF {element.tag} attributes/element; export explicit local frames and supported static semantics first')
        if any(c.tag not in children.get(element.tag,set()) for c in element):
            raise ValueError(f'Unsupported MJCF child of {element.tag}; no model semantics are silently discarded')
        for singleton in ('inertial','compiler','option','asset','worldbody'):
            if len(element.findall(singleton))>1:raise ValueError(f'MJCF has duplicate {singleton} elements')
        if element.tag=='inertial' and {'diaginertia','fullinertia'}<=set(element.attrib):
            raise ValueError('MJCF inertial must choose diaginertia or fullinertia, not both')
    compiler=root.find('compiler')
    if compiler is not None:
        allowed={'angle','coordinate','meshdir'}
        if set(compiler.attrib)-allowed or compiler.get('coordinate','local')!='local':
            raise ValueError('MJCF compiler transforms/inertia inference are not supported; export local frames and explicit inertials')
    angle=compiler.get('angle','degree') if compiler is not None else 'degree'
    if angle not in ('degree','radian'):raise ValueError('MJCF angle must be degree or radian')
    factor=np.pi/180 if angle=='degree' else 1.
    world=root.find('worldbody')
    if world is None:raise ValueError('MJCF needs worldbody')
    supplied={}
    if inertials:
        supplied=json.loads(Path(inertials).read_text(encoding='utf-8-sig'))
        if not isinstance(supplied,dict):raise ValueError('inertials must map MJCF body names to explicit records')
    assets={};mesh_copies={};sources={str(path):sha256(path)}
    if inertials:sources[str(Path(inertials).resolve())]=sha256(Path(inertials))
    for asset in root.findall('asset/mesh'):
        if set(asset.attrib)-{'name','file','scale'}:raise ValueError('MJCF mesh supports file/scale only; bake mesh reference transforms first')
        name=asset.get('name');file=asset.get('file')
        if not name or name in assets or not file:raise ValueError('MJCF mesh assets need unique names and files')
        mesh=(path.parent/(compiler.get('meshdir','') if compiler is not None else '')/file).resolve()
        if not mesh.is_file():raise ValueError(f'Missing MJCF mesh: {mesh}')
        scale=_vec(asset.get('scale'),default=[1,1,1])
        if np.any(scale<=0):raise ValueError('MJCF mesh scale must be positive')
        assets[name]=(mesh,scale);sources[str(mesh)]=sha256(mesh)
        # CAD Viewer's URDF renderer does not reliably handle native OBJ assets.
        # Package a standard binary STL for display, preserving coordinates and
        # the explicit MJCF scale. It never becomes component FEM geometry.
        mesh_copies[mesh]=Path('meshes')/(sources[str(mesh)]+('.stl' if mesh.suffix.lower()=='.obj' else mesh.suffix.lower()))
    urdf=XML.Element('robot',name=root.get('model','mjcf'))
    urdf.append(XML.Comment(' Design ledger: explicit local MJCF pos/quaternion tree, SI frames, one scalar joint per body. Joint anchor shifts are applied consistently to inertials, meshes and child frames. Inertials come from explicit input; actuator ratings and joint stiffness are not inferred. Mesh scale is preserved. This is a fixed-pose analysis handoff, not a dynamics model. '))
    mapping={};used=set();massless=[];joint_names=set()

    def visit(body,parent=None,parent_shift=None):
        name=body.get('name') if parent is not None else '__mjcf_world__'
        if not name or name in used:raise ValueError('MJCF bodies need unique names')
        used.add(name)
        if body.get('mocap','false')!='false' or float(body.get('gravcomp','0'))!=0:
            raise ValueError('MJCF mocap/gravity compensation cannot be mapped to passive URDF statics')
        joints=body.findall('joint')
        if len(joints)>1 or (parent is None and joints):raise ValueError('MJCF handoff supports one scalar joint per non-world body')
        j=joints[0] if joints else None
        shift=_vec(j.get('pos')) if j is not None else np.zeros(3)
        link=XML.SubElement(urdf,'link',name=name)
        inertial=body.find('inertial')
        record=supplied.get(name)
        if record is not None:
            if inertial is not None:raise ValueError(f'{name}: supplied inertial would override MJCF inertial; choose one source')
            if not record.get('source'):raise ValueError(f'{name}: inertial record needs a source')
            mass=number(record['mass_kg'],'mass_kg',True);com=np.array(vector(record['com_m'],'com_m'))
            tensor=np.array(record['inertia_kg_m2'],float)
            if tensor.shape!=(3,3) or not np.isfinite(tensor).all() or not np.allclose(tensor,tensor.T):raise ValueError('inertia must be a finite symmetric 3x3 tensor')
        elif inertial is not None:
            mass=number(float(inertial.get('mass')),'MJCF mass',True);frame=_frame(inertial);com=frame[:3,3]
            if inertial.get('diaginertia'):
                tensor=frame[:3,:3]@np.diag(_vec(inertial.get('diaginertia')))@frame[:3,:3].T
            elif inertial.get('fullinertia'):
                if 'quat' in inertial.attrib:raise ValueError('MJCF fullinertia is in body axes; do not also supply quat')
                a,b,c,d,e,f=_vec(inertial.get('fullinertia'),6);tensor=np.array([[a,d,e],[d,b,f],[e,f,c]])
            else:raise ValueError('MJCF inertial needs diaginertia or fullinertia')
        elif parent is None:
            mass=0;com=np.zeros(3);tensor=np.zeros((3,3));massless.append(name)
        else:
            raise ValueError(f'{name}: explicit inertial is missing. Supply --inertials JSON with mass_kg, com_m, inertia_kg_m2 and source for each body; CAD density/default density is not verified mass data.')
        if mass:
            node=XML.SubElement(link,'inertial');frame=np.eye(4);frame[:3,3]=com-shift;_origin(node,frame)
            XML.SubElement(node,'mass',value=str(mass))
            XML.SubElement(node,'inertia',**{k:str(tensor[i,j]) for k,i,j in [('ixx',0,0),('iyy',1,1),('izz',2,2),('ixy',0,1),('ixz',0,2),('iyz',1,2)]})
        for geom in body.findall('geom'):
            if geom.get('type','mesh')!='mesh' or geom.get('mesh') not in assets:
                raise ValueError('MJCF handoff supports file mesh geoms; export primitive geometry to mesh first')
            visual=XML.SubElement(link,'visual');frame=_frame(geom);frame[:3,3]-=shift;_origin(visual,frame)
            geometry=XML.SubElement(visual,'geometry');mesh,scale=assets[geom.get('mesh')]
            XML.SubElement(geometry,'mesh',filename=mesh_copies[mesh].as_posix(),scale=_text(scale))
        mapping[name]={'mjcf_body_from_urdf_link':{'xyz_m':shift.tolist(),'rpy_rad':[0,0,0]},
                       'inertial_source':record.get('source') if record else 'MJCF explicit inertial' if inertial is not None else 'fixed world reference'}
        if parent is not None:
            t=_frame(body);t[:3,3]+=t[:3,:3]@shift-parent_shift
            kind='fixed';attrs={}
            jname=j.get('name') if j is not None else name+'__fixed'
            if not jname or jname in joint_names:raise ValueError('MJCF joints need unique names')
            joint_names.add(jname)
            if j is not None:
                if set(j.attrib)-{'name','type','pos','axis','limited','range'}:
                    raise ValueError('MJCF joint ref, stiffness, damping, friction and other dynamics require an explicit supported model; none are silently dropped')
                if j.get('type','hinge') not in ('hinge','slide'):raise ValueError('Only hinge/slide MJCF joints are supported')
                limited=j.get('limited','auto')
                if limited not in ('true','false','auto'):raise ValueError('Invalid MJCF limited flag')
                bounded=limited=='true' or (limited=='auto' and 'range' in j.attrib)
                kind=('revolute' if bounded else 'continuous') if j.get('type','hinge')=='hinge' else 'prismatic'
                if kind=='prismatic' and not bounded:raise ValueError('Supply explicit slide range for URDF prismatic handoff')
                axis=_vec(j.get('axis'),default=[0,0,1])
                if np.linalg.norm(axis)==0:raise ValueError('MJCF joint axis is zero')
                if bounded:
                    if 'range' not in j.attrib:raise ValueError('A limited MJCF joint needs an explicit range; no zero-width range is inferred')
                    limits=_vec(j.get('range'),2)* (factor if kind=='revolute' else 1.)
                    if limits[0]>=limits[1]:raise ValueError('MJCF joint range needs lower < upper')
                    attrs={'lower':str(limits[0]),'upper':str(limits[1])}
                mapping[name]['joint_axis']=list(axis/np.linalg.norm(axis))
            joint=XML.SubElement(urdf,'joint',name=jname,type=kind)
            XML.SubElement(joint,'parent',link=parent);XML.SubElement(joint,'child',link=name);_origin(joint,t)
            if j is not None:XML.SubElement(joint,'axis',xyz=_text(axis))
            if attrs:XML.SubElement(joint,'limit',**attrs)
        for child in body.findall('body'):visit(child,name,shift)

    visit(world)
    if set(supplied)-used:raise ValueError('Inertial records reference unknown MJCF bodies')
    out.mkdir(parents=True)
    if mesh_copies:(out/'meshes').mkdir()
    for source,relative in mesh_copies.items():
        if source.suffix.lower()=='.obj':
            import trimesh
            surface=trimesh.load(source,force='mesh',process=False)
            if surface.is_empty or not np.isfinite(surface.vertices).all():raise ValueError('MJCF OBJ has no finite display triangles')
            surface.export(out/relative,file_type='stl')
        else:shutil.copyfile(source,out/relative)
    destination=out/'unvalidated.urdf';XML.indent(urdf);XML.ElementTree(urdf).write(destination,encoding='utf-8',xml_declaration=True)
    from .robot import read_urdf
    robot=read_urdf(destination,massless_links=massless)
    frame_checks=[]
    if reference:
        reference_hash=sha256(Path(reference))
        native=json.loads(Path(reference).read_text(encoding='utf-8-sig'))
        if native.get('mjcf_sha256')!=sources[str(path)]:raise ValueError('Native CAD reference belongs to another MJCF hash')
        from .robot import forward_kinematics
        kin=forward_kinematics(robot,{n:0. for n,j in robot['joints'].items() if j['type']!='fixed' and not j['mimic']})
        records=native.get('native_joint_frames',[])
        actual={n for n,j in robot['joints'].items() if j['type']!='fixed'}
        if {r['joint_name'] for r in records}!=actual or len(records)!=len(actual):
            raise ValueError('Native CAD reference must cover each moving joint exactly once')
        for r in records:
            j=robot['joints'][r['joint_name']];t=kin['frames'][j['child']]
            position=float(np.linalg.norm(t[:3,3]*1000-np.array(vector(r['origin_world_mm'],'reference origin'))))
            a=np.array(vector(r['axis_world'],'reference axis'));a=a/np.linalg.norm(a)
            angle=float(np.degrees(np.arccos(np.clip(np.dot(t[:3,:3]@j['axis'],a),-1,1))))
            if not np.isfinite(angle) or position>.1 or angle>.5:raise ValueError(f'CAD/URDF joint {j["name"]} differs by {position:g} mm / {angle:g} degrees; regenerate from native CAD')
            frame_checks.append({'joint':j['name'],'position_error_mm':position,'axis_error_deg':angle})
        sources[str(Path(reference).resolve())]=reference_hash
    if any(sha256(Path(p))!=h for p,h in sources.items()):raise ValueError('MJCF input changed during handoff')
    destination=destination.rename(out/'robot.urdf')
    report={'status':'converted','urdf':str(destination),'massless_links':massless,'source_files_sha256':sources,
            'source_gravity_m_s2':_vec(root.find('option').get('gravity'),default=[0,0,-9.81]).tolist() if root.find('option') is not None else [0.,0.,-9.81],
            'output_files_sha256':{p.relative_to(out).as_posix():sha256(p) for p in [destination,*[out/r for r in mesh_copies.values()]]},
            'native_cad_frame_checks':frame_checks,'cad_frame_consistency_checked':reference is not None,
            'links':mapping,'joint_count':len(robot['joints']),'whole_product_pass_available':False,
            'limitations':['Tree/frame/inertial translation only; not a dynamics simulation.',
                           'OBJ display geometry is packaged as binary STL with unchanged coordinates/scale; display materials are not transferred. These meshes are not FEM geometry.',
                           'MJCF gravity is recorded for explicit use in the analysis case; URDF does not encode it. Geom contact flags/materials are display-only here; contact dynamics are not transferred. Explicit body inertials take precedence over geom density/mass.',
                           'Actuator ratings and measured joint stiffness must be supplied separately; effort is not stiffness.',
                           'Visual meshes are not component FEM geometry; provide per-link STEP and explicit ports.']}
    write_json(out/'handoff.json',report);return report
