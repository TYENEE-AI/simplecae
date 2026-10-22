"""Native SimpleCADAPI handoff. Import this in the CAD environment, not CAE.

Only stdlib is imported until an export is requested. No solver or foreign OCP
runtime is loaded. A package alone cannot recover trustworthy native selections.
"""
from pathlib import Path
from importlib.metadata import version
from types import SimpleNamespace
import hashlib
import json
import math
import ast


class HandoffError(ValueError):
    def __init__(self, message, *, code='invalid_handoff', details=None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


def _write(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False)+'\n', encoding='utf-8')


def _hash(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _notebook_provenance(run, occurrence):
    config=getattr(run,'config',None)
    if config is None:return {}
    source=Path(config.path)
    paths={source}|{Path(p) for p in getattr(run,'dependencies',()) if Path(p).suffix=='.py'}
    hashes={str(p.resolve()):_hash(p) for p in sorted(paths) if p.is_file()}
    # Conservatively scope semantic continuity to unchanged notebook sources.
    # --set/--id may change; editing selector code requires an explicit new contract.
    names=[]
    tree=ast.parse(source.read_text(encoding='utf-8-sig'))
    bindings={}
    for assignment in ast.walk(tree):
        if isinstance(assignment,(ast.Assign,ast.AnnAssign)):
            targets=assignment.targets if isinstance(assignment,ast.Assign) else [assignment.target]
            if isinstance(assignment.value,ast.Call):
                bindings[id(assignment.value)]=[t.id for t in targets if isinstance(t,ast.Name)]
    for node in ast.walk(tree):
        if (isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr=='var'
                and node.args and isinstance(node.args[0],ast.Constant) and isinstance(node.args[0].value,str)):
            names.append((node.args[0].value,bindings.get(id(node),[])))
    parameters={}
    for n,aliases in names:
        key=next((key for key in [*aliases,n] if key in run.values),None)
        if key is None:continue
        value=run.values[key]
        if isinstance(value,(str,int,float,bool,type(None))):parameters[n]=value
        elif type(value).__name__=='Var' and type(value).__module__.startswith('simplecadapi.'):
            # Native Var defaults retain the declared units; float(value)
            # evaluates canonical units and would misreport --set inputs.
            parameters[n]=value.default
    return {'source_file':str(source.resolve()),'source_files_sha256':hashes,
            'parameters':parameters,'semantic_family':{'source_files_sha256':hashes,'occurrence':occurrence}}


def _identity():
    return [[1.,0.,0.,0.], [0.,1.,0.,0.], [0.,0.,1.,0.], [0.,0.,0.,1.]]


def _multiply(a, b):
    return [[sum(a[i][k]*b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def _transform(matrix, vector, point=True):
    return [sum(matrix[i][j]*vector[j] for j in range(3))+(matrix[i][3] if point else 0.) for i in range(3)]


def _selected(product, occurrence):
    from simplecadapi.product.part import Part
    from simplecadapi.product.assembly import Assembly
    matrix = _identity()
    labels = [product.name or (product.part_id if isinstance(product, Part) else product.assembly_id)]
    if isinstance(product, Assembly):
        if not occurrence:
            raise HandoffError('Assembly export requires an exact occurrence component path.', code='select_occurrence')
        for component_id in occurrence.split('/'):
            if not isinstance(product, Assembly):
                raise HandoffError('Occurrence path continues beyond a part.')
            candidates = [c for c in product.components if c.component_id == component_id]
            if len(candidates) != 1:
                raise HandoffError(f'Unknown occurrence component {component_id!r}.', details={'available': [c.component_id for c in product.components]})
            component = candidates[0]
            p = component.placement
            transform = [[p.x_axis[i],p.y_axis[i],p.z_axis[i],p.origin[i]] for i in range(3)]+[[0.,0.,0.,1.]]
            matrix = _multiply(matrix, transform)
            product = component.item
            labels += [component.name or component.component_id,
                       product.name or (product.part_id if isinstance(product, Part) else product.assembly_id)]
    elif occurrence:
        raise HandoffError('A single part has no occurrence path.')
    if not isinstance(product, Part):
        raise HandoffError('Select a leaf part occurrence, not an assembly.')
    # These are the exact XCAF names used by the native STEP exporter. The CAE
    # importer verifies this label and the complete file hash before any binding.
    return product, matrix, 'Shapes/'+'/'.join(labels)


def _signature(face, matrix, world):
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    surface = BRepAdaptor_Surface(face.wrapped)
    kind = str(surface.GetType()).split('.')[-1].removeprefix('GeomAbs_')
    kinds = {'BSplineSurface':'BSpline surface', 'BezierSurface':'Bezier surface',
             'SurfaceOfRevolution':'Surface of Revolution', 'SurfaceOfExtrusion':'Surface of Extrusion'}
    center = [float(v) for v in face.get_center()]
    result = {'centroid_mm': _transform(matrix,center) if world else center,
              'area_mm2': float(face.get_area()), 'surface_type': kinds.get(kind,kind),
              'native_face_id': str(face.topo_id)}
    if kind == 'Plane':
        normal = [float(v) for v in face.get_normal_at()]
        result['normal_hint'] = _transform(matrix,normal,False) if world else normal
    if not all(math.isfinite(v) for v in result['centroid_mm']) or not result['area_mm2'] > 0:
        raise HandoffError('Native selection contains a degenerate or nonfinite face.')
    return result


def export_for_cae(result, out_dir='out/cae', *, required, frame='part_local', occurrence=None):
    """Export a completed NotebookRun, Part/AssemblyBuildResult or native product.

    Run after the final geometry/tagging operation and notebook projection. For a
    notebook use ``export_for_cae(run_notebook(path), ...)``; a built child returned
    by ``scad.use`` may also be passed from a notebook's final export cell.
    ``required`` maps interface.* tags to expected face_count and surface_types.
    A fresh output directory prevents stale successful manifests after a failure.
    """
    if isinstance(result, (str, Path)):
        raise HandoffError('A .scadpkg is not a native selection source. Rerun its source notebook in the SimpleCADAPI environment, then export_for_cae(run_notebook(source), ...). Do not read package BREP or guess face_N.', code='rerun_source_notebook')
    if frame not in ('part_local','world'):
        raise HandoffError('frame must be part_local or world')
    if not isinstance(required, dict) or not required:
        raise HandoffError('required must map interface.<region> to face_count and optional surface_types')
    for tag, spec in required.items():
        if not isinstance(tag,str) or not tag.startswith('interface.') or not tag[10:]:
            raise HandoffError('Required tags must use interface.<region>; the package does not preserve cae.* tags.')
        if (not isinstance(spec,dict) or set(spec)-{'face_count','surface_types'} or
            type(spec.get('face_count')) is not int or spec['face_count'] < 1):
            raise HandoffError(f'{tag}: expected a positive face_count and optional surface_types list')
        if 'surface_types' in spec and (not isinstance(spec['surface_types'],list) or
            not spec['surface_types'] or any(not isinstance(v,str) or not v for v in spec['surface_types'])):
            raise HandoffError(f'{tag}.surface_types must be a nonempty list of type names')
    out = Path(out_dir).resolve()
    if out.exists() and any(out.iterdir()):
        raise HandoffError('Use a fresh handoff directory for each revision; existing evidence will not be overwritten.', code='output_exists')
    out.mkdir(parents=True, exist_ok=True)
    report = {'status':'invalid', 'generator':'simplecadapi', 'generator_version':version('simplecadapi'),
              'frame':frame, 'occurrence':occurrence, 'required':required, 'regions':{},
              'engineering_acceptance':False}
    try:
        import simplecadapi as scad
        from simplecadapi.artifacts.assembly_io import attached_definition
        product = getattr(result,'product',None) or getattr(result,'value',None) or result
        definition = getattr(result,'definition',None) or attached_definition(product)
        if definition is None:
            raise HandoffError('Native product has not been projected yet. Finish sca run / run_notebook, then pass the NotebookRun to export_for_cae; do not export an unfinished cell.', code='finish_native_notebook')
        selected, matrix, label = _selected(product,occurrence)
        selected_definition = attached_definition(selected)
        if selected_definition is None:
            raise HandoffError('Selected native part has no source definition; rebuild its source notebook.')
        regions = {}
        failures = []
        for tag, spec in required.items():
            query = scad.ql.faces().where(scad.ql.tag(tag))
            faces = query.resolve(selected.body)
            signatures = [_signature(f,matrix,frame=='world') for f in faces]
            report['regions'][tag] = {'expected':spec,'actual_count':len(faces),'faces':signatures}
            kinds = [k.lower() for k in spec.get('surface_types',[])]
            if len(faces)!=spec['face_count'] or (kinds and any(f['surface_type'].lower() not in kinds for f in signatures)):
                failures.append(tag)
            regions[tag.removeprefix('interface.')] = {'face_count':spec['face_count'],
                'surface_types':spec.get('surface_types') or sorted({f['surface_type'] for f in signatures}),
                'faces':signatures,'native_selector':query.to_dict()}
        if failures:
            raise HandoffError('Missing, excess or wrong-type native interface faces: '+', '.join(failures)+'. Tags may have been cleared by later features; apply interface.* tags after the final fillet/partition, then rerun and re-export.',
                               code='native_interface_mismatch',details={'failed_tags':failures})
        captured = scad.capture(SimpleNamespace(value=product,definition=definition),out/'source.scadpkg',include_scene=False)
        step = out/'part.step'
        export = scad.exporter.export_product_package_to_step(captured.package,step)
        provenance = {'generator':'simplecadapi','generator_version':report['generator_version'],
                      'definition_id':selected_definition.definition_id,'revision':selected_definition.revision,
                      'content_hash':_hash(step),'package_id':captured.package.root_id,
                      'package_version':str(captured.package.manifest['schema_version']),
                      'package_sha256':_hash(out/'source.scadpkg')}
        provenance.update(_notebook_provenance(result,occurrence))
        material_ref=getattr(selected_definition,'material_ref',None)
        if material_ref is not None:provenance['cad_material_label']=material_ref.material_id
        material=getattr(selected,'material',None)
        if material is not None:
            provenance['cad_material_label']=material.name or material.material_id
            if material.density is not None:
                factors={'kg/m^3':1.,'kg/m3':1.,'g/cm^3':1000.,'g/cm3':1000.,'kg/mm^3':1e9,'kg/mm3':1e9}
                if material.density_unit not in factors:
                    raise HandoffError('Unsupported explicit CAD density unit: '+str(material.density_unit)+'. Normalize CAD density to kg/m^3 before export; no mechanical properties are inferred.')
                provenance['cad_density_kg_m3']=material.density*factors[material.density_unit]
        manifest = {'schema':'simplecae.interface_manifold/2','frame':frame,
                    'part':{'step_label':label} if occurrence else {'solid_id':1},
                    'placement':{'source':'native_occurrence','matrix_4x4':matrix},
                    'provenance':provenance,'regions':regions}
        report.update(status='exported',provenance=provenance,export=export.to_dict(),
                      native_definition_hash=selected_definition.content_hash,
                      artifacts=['part.step','source.scadpkg','interface_manifold.json'],
                      next_action='bind-regions and review the boundary preview before solving')
        _write(out/'interface_manifold.json',manifest)
    except Exception as exc:
        report['status']='invalid'
        report['error'] = {'code':getattr(exc,'code','native_export_failed'),'message':str(exc),'details':getattr(exc,'details',{})}
        raise
    finally:
        _write(out/'handoff_report.json',report)
    return report
