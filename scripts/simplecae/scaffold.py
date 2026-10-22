"""Small task presets. Unknown physics stays pending; no safety data is guessed."""
from pathlib import Path
import copy
import json
from .case import CONDITIONS,write_json,number,vector

MATERIALS={'reference-steel':{'name':'mathematical_isotropic_reference',
    'youngs_modulus_mpa':200000.,'poisson_ratio':.3,'yield_strength_mpa':200.,
    'failure_criterion':'von_mises_yield',
    'source':'Prescribed mathematical benchmark constants, as in examples/integration/simplecad-beam-step.case.json. Not an actual steel grade or material certificate.'}}


def scaffold(out, *, preset, material, model=None, interfaces=None, force_n=None,
             max_displacement_mm=None, safety_factor=2., task_id=None, mesh_sizes=None):
    if preset not in ('hook','bracket','plate'):raise ValueError('preset must be hook, bracket or plate')
    if material in MATERIALS:
        properties=copy.deepcopy(MATERIALS[material]);material_source=None
    elif Path(material).is_file():
        material_source=Path(material).resolve()
        properties=json.loads(material_source.read_text(encoding='utf-8-sig'))
        from .materials import validate_material
        validate_material(properties)
    else:
        raise ValueError('material: choose reference-steel for a mathematical test, or supply a material JSON file with explicit mechanical properties and source. CAD labels such as 6061 or PLA are not a material-data source.')
    out=Path(out).resolve()
    if out.exists():raise ValueError('Scaffold output directory must be fresh')
    missing=[]
    for label,value in [('model',model),('interfaces',interfaces)]:
        if value is None:missing.append(label)
        elif not Path(value).is_file():raise ValueError(f'{label}: file does not exist: {value}')
    if force_n is None:missing.append('force_n')
    else:vector(force_n,'force_n')
    if max_displacement_mm is None:missing.append('max_displacement_mm')
    else:number(max_displacement_mm,'max_displacement_mm',True)
    if number(safety_factor,'safety_factor')<1:raise ValueError('safety_factor must be >=1')
    ready=not missing
    task_id=task_id or f'{preset}-static-screen'
    assumptions=['Agent screening assumption: ideal clamp on interface.mount and stated force on interface.payload; verify these represent the actual installation.',
                 'Linear small-strain isotropic/declared calibrated material model; no automatic product qualification.',
                 f'Declared screening yield safety factor: {safety_factor:g}.']
    exclusions=['Anchors, fasteners and actual mounting compliance','Manufacturing/material variability',
                'Fatigue, impact, buckling and sustained-temperature creep unless separately assessed']
    check={'id':'body-static','scenario':'use','question':f'Does the {preset} body meet the declared static strength and deflection limits?',
        'user_impact':'Excess deformation or stress may prevent the declared use.',
        'method':'fem','decision':'now' if ready else 'needs_information','targets':[f'{preset} load-bearing body'],
        'reason':'Target the load path; a body result does not qualify installation or product.',
        'required_for_claim':True,'acceptance':'Use the explicit case strength and displacement limits without changing loads to pass.',
        'assumptions':assumptions,'not_assessed':exclusions}
    if ready:
        check.update(load_path='Payload patch through the body to the mounting patch.',
                     load_basis=f'Declared total force {force_n} N; no load inferred from geometry.',
                     support_basis='Explicit ideal fixed interface.mount; applicability is unverified.',
                     result_criteria=['strength','stiffness'])
    external={'id':'installation-evidence','scenario':'use','question':'Are material, mounting and other required use checks supported?',
        'user_impact':'A body-only pass cannot establish product performance.','method':'information','decision':'needs_information',
        'targets':['Material/manufacturing and installation'],'reason':'Physical applicability is not established by a preset.',
        'required_for_claim':True,'acceptance':'Obtain applicable evidence and add any missing use-specific checks.',
        'assumptions':[],'not_assessed':['Whole product qualification']}
    task={'schema_version':'simplecae-task-1.0','task_id':task_id,
        'request':f'Preliminary {preset} static body screen; complete missing use conditions before any product claim.',
        'scenarios':[{'id':'use','use':f'{preset} under explicitly declared loading',
                      'success':'Body strength and deflection meet the supplied criteria, with installation evidence tracked separately.'}],
        'checks':[check,external],'unknowns':missing+['Physical applicability of material and mounting'],
        'iteration_constraints':['Keep load, material, supports and acceptance fixed across CAD comparisons.'],
        'sources':['task.json'],'cases':{}}
    case=None
    if ready:
        if mesh_sizes is None:
            from .geometry import session,inventory
            spec={'path':str(Path(model).resolve()),'interface_manifest':str(Path(interfaces).resolve())}
            with session(Path(spec['path']),spec) as g:info=inventory(g,Path(spec['path']))
            extent=min(hi-lo for hi,lo in zip(info['bbox_mm'][1],info['bbox_mm'][0]))
            mesh_sizes=[float(format(extent*.5*.75**i,'.6g')) for i in range(3)]
        case={'schema_version':'2.0','model':{'path':str(Path(model).resolve()),'interface_manifest':str(Path(interfaces).resolve())},
              'material':properties,'supports':[{'name':'mount','selector':{'type':'interface','name':'mount'}}],
              'loads':[{'name':'payload','selector':{'type':'interface','name':'payload'},'total_force_n':force_n}],
              'criteria':{'yield_safety_factor':safety_factor,'max_displacement_mm':max_displacement_mm},
              'mesh':{'sizes_mm':mesh_sizes},'conditions':{key:False for key in CONDITIONS},
              'notes':'Preset is an explicit preliminary model; inspect load mapping and boundary preview. Mesh sizes are a planning starting point.',
              'provenance':{'task_id':task_id,'generator':'custom','model_id':task_id,'revision':'initial'}}
        manifest=json.loads(Path(interfaces).read_text(encoding='utf-8-sig'))
        if manifest.get('schema')=='simplecae.interface_manifold/2':
            from .bridge import manifest_identity
            identity=manifest_identity(manifest)
            native=manifest['provenance']
            case['provenance'].update({k:identity[k] for k in ('generator','generator_version','model_id','revision')})
            case['provenance'].update({k:native[k] for k in ('parameters','source_file') if k in native})
        from .case import validate_case
        from .schemas import check_contract
        check_contract(case);validate_case(case)
        task['cases']['body-static']='case.json'
        task['sources'] += [case['model']['path'],case['model']['interface_manifest']]
    if material_source:task['sources'].append(str(material_source))
    out.mkdir(parents=True)
    if case:write_json(out/'case.json',case)
    write_json(out/'task.json',task)
    report={'task':str(out/'task.json'),'case':str(out/'case.json') if case else None,'ready_for_body_check':ready,
            'missing_inputs':missing,'material_source':properties['source'],'worker_started':False,'whole_product_pass_available':False,
            'next_action':'Review preview, assumptions and material applicability, then task start/run.' if ready else
                          'Supply the missing flags and rerun scaffold to a fresh directory; the current task can record the pending information.'}
    write_json(out/'scaffold-report.json',report);return report
