"""Versioned JSON syntax contracts. Physical/model validation remains separate."""
from pathlib import Path
import json
from .case import CONDITIONS

N={'type':'number'};P={'type':'number','exclusiveMinimum':0};S={'type':'string','minLength':1};B={'type':'boolean'}
V={'type':'array','items':N,'minItems':3,'maxItems':3}
def arr(item,minimum=0):return {'type':'array','items':item,'minItems':minimum}
def obj(properties,required=()):return {'type':'object','properties':properties,'required':list(required),'additionalProperties':False}
def ref(name):return {'$ref':'#/$defs/'+name}
def enum(*values):return {'enum':list(values)}


def contracts():
    defs={}
    defs['selector']={'oneOf':[
        obj({'type':{'const':'plane'},'axis':enum('x','y','z'),'position_mm':N,'tolerance_mm':P},('type','axis','position_mm')),
        obj({'type':{'const':'face_ids'},'ids':{'type':'array','items':{'type':'integer','minimum':1},'minItems':1,'uniqueItems':True},'geometry_sha256':{'type':'string','pattern':'^[0-9a-fA-F]{64}$'}},('type','ids','geometry_sha256')),
        obj({'type':{'const':'interface'},'name':S},('type','name'))]}
    defs['model']=obj({'path':S,'expected_bbox_mm':{'type':'array','items':V,'minItems':2,'maxItems':2},'units':enum('m','mm','cm'),'source_up_axis':enum('y','z'),'scene_node':S,'pose':enum('rest'),'interface_manifest':S,
        'solid_id':obj({'id':{'type':'integer','minimum':1},'geometry_sha256':{'type':'string','pattern':'^[0-9a-fA-F]{64}$'}},('id','geometry_sha256'))},('path',))
    constants=('e1_mpa','e2_mpa','e3_mpa','nu12','nu13','nu23','g12_mpa','g13_mpa','g23_mpa')
    material={'name':S,'source':S,'elastic_model':enum('isotropic','orthotropic'),'youngs_modulus_mpa':P,'poisson_ratio':{'type':'number','exclusiveMinimum':-1,'exclusiveMaximum':.5},'yield_strength_mpa':{'anyOf':[P,{'type':'null'}]},'failure_criterion':enum('not_specified','von_mises_yield','max_stress'),'density_kg_m3':P,
        'engineering_constants':obj({k:P if k.startswith(('e','g')) else N for k in constants},constants),
        'orientation':obj({'axis_1':V,'axis_2':V},('axis_1','axis_2')),
        'strengths':obj({k:dict(V,items=P) for k in ('tension_mpa','compression_mpa','shear_mpa')},('tension_mpa','compression_mpa','shear_mpa')),
        'calibration':obj({'kind':enum('coupon_tests','literature','mathematical_reference'),'reference':S,'applicability':S},('kind','reference','applicability'))}
    defs['material']=obj(material,('name','source'));defs['material']['allOf']=[{'if':{'properties':{'elastic_model':{'const':'orthotropic'}},'required':['elastic_model']},'then':{'required':['engineering_constants','orientation']},'else':{'required':['youngs_modulus_mpa','poisson_ratio']}}]
    dofs={'type':'array','items':{'type':'integer','minimum':1,'maximum':3},'minItems':1,'maxItems':3,'uniqueItems':True}
    defs['support']=obj({'name':S,'selector':ref('selector'),'dofs':dofs},('name','selector'))
    reference_support=obj({'name':S,'point_mm':V,'dofs':dofs,'geometry_sha256':{'type':'string','pattern':'^[0-9a-fA-F]{64}$'}},('name','point_mm','dofs','geometry_sha256'))
    force={'name':S,'selector':ref('selector'),'total_force_n':V,'total_moment_n_mm':V,'application_point_mm':V,'scalable':B}
    defs['load']=obj(force,('name','selector','total_force_n'))
    defs['criteria']=obj({'yield_safety_factor':{'anyOf':[{'type':'number','minimum':1},{'type':'null'}]},'strength_safety_factor':{'type':'number','minimum':1},'max_displacement_mm':{'anyOf':[P,{'type':'null'}]},'max_small_displacement_ratio':P,'max_strain_norm':P})
    local=obj({'name':S,'selector':ref('selector'),'size_factor':{'type':'number','exclusiveMinimum':0,'maximum':1},'distance_mm':P,'sampling':{'type':'integer','minimum':10,'maximum':500}},('name','selector','size_factor','distance_mm'))
    defs['mesh']=obj({'sizes_mm':arr(P,3),'displacement_relative_tolerance':P,'stress_relative_tolerance':P,'balance_relative_tolerance':P,'max_elements':{'type':'integer','minimum':1},'local_refinements':arr(local),'preserve_boundary_nodes':B},('sizes_mm',))
    defs['conditions']=obj({k:B for k in CONDITIONS},CONDITIONS)
    defs['gravity']=obj({'acceleration_m_s2':V},('acceleration_m_s2',))
    defs['buckling']=obj({'enabled':B,'modes':{'type':'integer','minimum':1,'maximum':20},'safety_factor':{'type':'number','minimum':1},'eigenvalue_relative_tolerance':P},('enabled',))
    defs['provenance']=obj({k:{} for k in ('generator','model_id','revision','parameters','task_id','source_file','generator_version')})
    probe_common={'name':S,'direction':V,'max_displacement_mm':P,'absolute_convergence_tolerance_mm':P,'convergence_required':B}
    defs['probe']={'oneOf':[obj(dict(probe_common,type={'const':'point'},point_mm=V,body=S),('name','type','point_mm')),
        obj(dict(probe_common,type={'const':'surface_average'},selector=ref('selector'),body=S),('name','type','selector')),
        obj(dict(probe_common,type=enum('relative','relative_length'),from_probe=S,to_probe=S),('name','type','from_probe','to_probe'))]}
    common={'schema_version':enum('1.0','2.0'),'reference_only':B,'model':ref('model'),'material':ref('material'),'supports':arr({'oneOf':[ref('support'),reference_support]},1),'loads':arr(ref('load')),'criteria':ref('criteria'),'mesh':ref('mesh'),'conditions':ref('conditions'),'notes':{},'gravity':ref('gravity'),'buckling':ref('buckling'),'provenance':ref('provenance'),
        'load_cases':arr(obj({'name':S,'loads':arr(ref('load')),'gravity':ref('gravity')},('name','loads')),1),'probes':arr(ref('probe'))}
    defs['solid']=obj(common,('schema_version','model','material','supports','loads','criteria','mesh','conditions'))
    defs['assembly_support']=obj({'name':S,'body':S,'selector':ref('selector'),'dofs':dofs},('name','body','selector'))
    defs['assembly_load']=obj(dict(force,body=S),('name','body','selector','total_force_n'))
    side=obj({'body':S,'selector':ref('selector')},('body','selector'))
    connection=obj({'name':S,'type':enum('bonded','linear_interface'),'master':side,'slave':side,'position_tolerance_mm':P,'normal':V,'normal_stiffness_n_mm3':P,'tangential_stiffness_n_mm3':P,'max_quadrature_points':{'type':'integer','minimum':1,'maximum':200000},'calibration':obj({'reference':S,'applicability':S},('reference','applicability'))},('name','type','master','slave'))
    body=obj({'name':S,'model':ref('model'),'material':ref('material'),'placement':obj({'translation_mm':V,'rpy_rad':V},('translation_mm','rpy_rad')),'mesh_size_factor':P,'local_refinements':defs['mesh']['properties']['local_refinements']},('name','model','material'))
    defs['assembly']=obj({'schema_version':{'const':'assembly-1.0'},'bodies':arr(body,2),'connections':arr(connection,1),'supports':arr(ref('assembly_support'),1),'loads':arr(ref('assembly_load')),'criteria':ref('criteria'),'mesh':ref('mesh'),'conditions':obj({k:B for k in (*CONDITIONS,'connection_parameters_verified')},(*CONDITIONS,'connection_parameters_verified')),'gravity':ref('gravity'),'buckling':ref('buckling'),'provenance':ref('provenance'),'notes':{},'probes':arr(ref('probe'))},('schema_version','bodies','connections','supports','loads','criteria','mesh','conditions'))
    stress_region=obj({'name':S,'min_mm':V,'max_mm':V,'body':S},('name','min_mm','max_mm'))
    defs['solid']['properties']['stress_regions']=arr(stress_region)
    defs['assembly']['properties']['stress_regions']=arr(stress_region)
    frame=obj({'xyz_m':V,'rpy_rad':V},('xyz_m','rpy_rad'))
    defs['robot_probe']={'oneOf':[obj(dict(probe_common,type={'const':'point'},point_m=V,link=S),('name','type','point_m','link')),
        obj(dict(probe_common,type={'const':'surface_average'},component_selector=ref('selector'),link=S),('name','type','component_selector','link')),
        obj(dict(probe_common,type={'const':'relative'},from_probe=S,to_probe=S),('name','type','from_probe','to_probe'))]}
    robot_conditions=('inertials_verified','actuator_ratings_verified','mount_verified','poses_verified')
    actuation_port=obj({'link':S,'point_link_m':V},('link','point_link_m'))
    defs['actuation_reaction']=obj({'name':S,'joint':S,'driven':actuation_port,'reaction':actuation_port,'verified':B,'reference':S},('name','joint','driven','reaction'))
    pad_contact=obj({'normal_load_name':S,'center_link_m':V,'tangent_u_link':V,'tangent_v_link':V,'half_extents_m':{'type':'array','items':P,'minItems':2,'maxItems':2}},('normal_load_name','center_link_m','tangent_u_link','tangent_v_link','half_extents_m'))
    defs['grasp']=obj({'model':enum('vertical_friction','finite_pad_wrench'),'pad_contacts':dict(arr(pad_contact,2),maxItems=2),'pad_wrench_mode':enum('declared_per_pad','total_wrench'),'payload_names':dict(arr(S,1),uniqueItems=True),'normal_load_names':dict(arr(S,2),maxItems=2,uniqueItems=True),
        'additional_tangential_load_names':dict(arr(S),uniqueItems=True),'friction_coefficient':{'type':'number','minimum':0},
        'slip_safety_factor':{'type':'number','minimum':1},'conditions':obj({'friction_verified':B,'force_verified':B,'pad_contact_verified':B},('friction_verified','force_verified'))},
        ('payload_names','normal_load_names','friction_coefficient','slip_safety_factor','conditions'))
    defs['robot']=obj({'schema_version':{'const':'robot-1.0'},'model':obj({'path':S,'package_roots':{'type':'object','additionalProperties':S}},('path',)),
        'poses':arr(obj({'name':S,'joints':{'type':'object','additionalProperties':N}},('name','joints')),1),'gravity_m_s2':V,'base_pose':frame,'massless_links':arr(S),
        'base':{'oneOf':[obj({'type':{'const':'fixed'}},('type',)),obj({'type':{'const':'contacts'},'points_world_m':arr(V,3),'friction_coefficient':P},('type','points_world_m','friction_coefficient'))]},
        'payloads':arr(obj({'name':S,'link':S,'mass_kg':P,'center_m':V,'scalable':B},('name','link','mass_kg','center_m'))),
        'loads':arr(obj({'name':S,'link':S,'force_n':V,'moment_n_m':V,'position_m':V,'frame':enum('link','world'),'position_frame':enum('link','world'),'scalable':B},('name','link','force_n','position_m'))),
        'effort_safety_factor':{'type':'number','minimum':1},'effort_limits':{'type':'object','additionalProperties':P},'conditions':obj({k:B for k in robot_conditions},robot_conditions),
        'components':arr(obj({'link':S,'case_path':S,'ports':{'type':'object','additionalProperties':ref('selector')},'mass_relative_tolerance':P,'com_tolerance_mm':P,'link_from_component':frame},('link','case_path','ports'))),'required_components':arr(S),'provenance':ref('provenance'),'grasp':ref('grasp'),'notes':{},'probes':arr(ref('robot_probe')),'actuation_reactions':arr(ref('actuation_reaction'))},('schema_version','model','poses','gravity_m_s2','base','conditions'))
    connection['properties']['type']=enum('bonded','linear_interface','frictionless_contact','frictional_contact')
    connection['properties'].update(friction_coefficient=P,max_tangential_displacement_mm=P,slip_convergence_tolerance_mm=P,initial_gap_mm={'type':'number','minimum':0},gap_convergence_tolerance_mm=P)
    connection['properties']['footprint']=enum('matching','slave_within_master')
    defs['assembly_support']['properties']['service_displacement_mm']=V
    bolt={'name':S,'master':side,'slave':side,'axis':V,'axial_stiffness_n_mm':P,'preload_n':P,'allowable_tension_n':P,'reference':S}
    defs['assembly']['properties']['bolts']=arr(obj(bolt,bolt),1)
    defs['assembly']['properties']['contact_control']=obj({'initial_increment':P,'minimum_increment':P,'maximum_increment':P,'service_initial_increment':P,'service_maximum_increment':P,'max_increments':{'type':'integer','minimum':1,'maximum':10000},'contact_change_relative_tolerance':{'type':'number','minimum':0,'maximum':.001}})
    elastic={'rigid_links':dict(arr(S),uniqueItems=True),'joints_locked_verified':B,'max_rotation_rad':{'type':'number','exclusiveMinimum':0,'maximum':.05},'max_section_warping_mm':P,'reference':S}
    defs['robot']['properties']['elastic_transfer']=obj(elastic,elastic)
    spring=obj({'rotational_stiffness_n_m_rad':P,'linear_stiffness_n_m':P,'reference':S,'verified':B},('reference','verified'))
    spring['oneOf']=[{'required':['rotational_stiffness_n_m_rad']},{'required':['linear_stiffness_n_m']}]
    transfer=defs['robot']['properties']['elastic_transfer']
    transfer['properties'].update(joint_compliance={'type':'object','minProperties':1,'additionalProperties':spring},
                                  rigid_joints=dict(arr(S),uniqueItems=True))
    transfer['dependentRequired']={'joint_compliance':['rigid_joints'],'rigid_joints':['joint_compliance']}
    header={'$schema':'https://json-schema.org/draft/2020-12/schema'}
    case=header|{'title':'SimpleCAE case: supported versioned syntax, with additional semantic checks by check/analyze','$defs':defs,'oneOf':[ref('solid'),ref('assembly'),ref('robot')]}
    status=enum('invalid','indeterminate','fail_under_stated_model','pass_under_stated_model')
    result=header|{'title':'SimpleCAE result envelope','type':'object','required':['schema_version','analysis','status','case','evaluation_signal'],'properties':{'schema_version':enum('1.0','2.0','assembly-1.0','robot-result-1.0'),'analysis':enum('linear_static','linear_static_assembly','load_case_envelope','urdf_static'),'status':status,'case':{'type':'object'},'evaluation_signal':{'type':'object'},'error':S},'additionalProperties':True,
                  'allOf':[{'if':{'properties':{'status':{'const':'invalid'}}},'then':{'required':['error']}}]}
    props={'schema_version':{'const':'simplecae-signal-1.0'},'analysis_status':status,'valid_for_comparison':B,'feasible_under_stated_model':{'type':['boolean','null']},'physical_conditions_verified':B,'whole_installation_rating_available':{'const':False},'task_contract_sha256':{'type':'string','pattern':'^[0-9a-f]{64}$'},'task_id':{},'candidate':{'type':'object'},'utilizations':{'type':'object','additionalProperties':{'type':'number','minimum':0}},'bottleneck_margin':{'type':['number','null'],'minimum':0},'metrics':{'type':'object'},'coverage':{'type':'object'},'conditional_limit':{'type':['object','null']},'feedback':arr({'type':'object','required':['kind'],'properties':{'kind':S}}),'not_assessed':arr(S),'score_meaning':S}
    signal=header|obj(dict(props,criterion_assessments={'type':'object'},whole_product_pass_available={'const':False}),props);signal['title']='SimpleCAE design signal';signal['allOf']=[{'if':{'properties':{'valid_for_comparison':{'const':False}}},'then':{'properties':{'bottleneck_margin':{'type':'null'},'feasible_under_stated_model':{'type':'null'}}}}]
    comparison=header|obj({'schema_version':{'const':'simplecae-comparison-1.0'},'comparable':B,'withheld_reasons':arr(S),'candidates':arr({'type':'object'},2),'meaning':S},('schema_version','comparable','withheld_reasons','candidates','meaning'))
    result['properties']['analysis']['enum'].extend(['frictionless_contact_assembly','staged_contact_assembly'])
    from .evidence import DOMAINS,STATES,KINDS
    hash_value={'type':'string','pattern':'^[0-9a-fA-F]{64}$'}
    file_reference=obj({'path':S,'sha256':hash_value},('path','sha256'))
    evidence_record=obj({'file':file_reference,'kind':enum(*KINDS),'applies_to':dict(arr(S,1),uniqueItems=True),
                         'source_sha256':{'type':'object','additionalProperties':hash_value},'scope':S,
                         'outcome':enum('pass','fail','inconclusive'),'date':S,'operator':S,'test_method':S},('file','kind','applies_to','source_sha256','scope'))
    ledger=header|obj({'schema_version':{'const':'simplecae-evidence-1.0'},'title':S,
                       'bindings':{'type':'object','minProperties':1,'additionalProperties':file_reference},
                       'items':arr(obj({'id':S,'domain':enum(*DOMAINS),'title':S,'state':enum(*STATES),'statement':S,'evidence':arr(evidence_record)},('id','domain','title','state','statement','evidence')),1),
                       'notes':{}},('schema_version','title','bindings','items'))
    ledger_review=header|{'type':'object','required':['schema_version','bindings','items','whole_product_rating_available','certification_available'],
                         'properties':{'schema_version':{'const':'simplecae-evidence-review-1.0'},'bindings':{'type':'object'},'items':arr({'type':'object'},1),
                                       'whole_product_rating_available':{'const':False},'certification_available':{'const':False}},'additionalProperties':True}
    nonnegative={'type':'number','minimum':0}
    extent=obj({'name':S,'type':{'const':'extent'},'axis':enum('x','y','z'),'expected_mm':P,'tolerance_mm':nonnegative},('name','type','axis','expected_mm','tolerance_mm'))
    axis_check=obj({'name':S,'type':{'const':'cylinder_axis'},'selector':ref('selector'),'expected_axis':V,'expected_point_mm':V,
                    'axis_distance_tolerance_mm':nonnegative,'angle_tolerance_deg':{'type':'number','minimum':0,'exclusiveMaximum':90},'expected_radius_mm':P,'radius_tolerance_mm':nonnegative},
                   ('name','type','selector','expected_axis','expected_point_mm','axis_distance_tolerance_mm','angle_tolerance_deg'))
    interface=header|obj({'schema_version':{'const':'simplecae-interface-1.0'},'model':ref('model'),
                          'provenance':obj({'classification':enum('manufacturer_cad','catalog_cad','interface_envelope','user_design'),'part_number':S,'source_url':S,
                                            'reference_document':file_reference,'reference_pages':arr({'type':'integer','minimum':1},1)},('classification','part_number','source_url','reference_document','reference_pages')),
                          'frame':obj({'xyz_mm':V,'rpy_rad':V},('xyz_mm','rpy_rad')),
                          'checks':arr({'oneOf':[extent,axis_check]},1),'notes':{}},('schema_version','model','provenance','checks'))
    interface['$defs']=defs
    family_case=obj({'name':S,'case_path':S,'case_sha256':hash_value,'case_relative_path':S,'normal_force_per_finger_n':P,'analysis_required':B,
                     'status':enum('not_run','invalid','indeterminate','fail_under_stated_model','pass_under_stated_model'),
                     'result_relative_path':S,'report_relative_path':S,'preview_relative_path':S,'valid_for_comparison':B,'physical_conditions_verified':B,'error':S},
                    ('name','case_path','case_sha256','case_relative_path','normal_force_per_finger_n','analysis_required','status'))
    family=header|obj({'schema_version':{'const':'simplecae-task-family-1.0'},'toolkit_version':S,'source_task':S,'source_task_sha256':hash_value,
                       'source_files_sha256':{'type':'object','additionalProperties':hash_value},'task_id':S,'cases':arr(family_case),
                       'whole_product_rating_available':{'const':False},'conditional_product_capacity_available':{'const':False},
                       'comparison_margin':{'type':'null'},'known_failures':arr({'type':'object'}),'scope':S,'status':status,'error':S,
                       'force_budget':{'type':'object'},'force_envelope_relative_path':S,'application_relative_path':S},
                      ('schema_version','toolkit_version','source_task','source_task_sha256','cases','whole_product_rating_available','conditional_product_capacity_available','comparison_margin','known_failures','scope','status'))
    family['allOf']=[{'if':{'properties':{'status':{'const':'invalid'}}},'then':{'required':['error']}}]
    task_pad=obj({k:v for k,v in pad_contact['properties'].items() if k!='normal_load_name'},('center_link_m','tangent_u_link','tangent_v_link','half_extents_m'))
    task_props={'schema_version':{'const':'gripper-task-1.0'},'task_id':S,'model_path':S,'package_roots':{'type':'object','additionalProperties':S},'massless_links':arr(S),
                'poses':defs['robot']['properties']['poses'],'contacts':dict(arr(obj({'link':S,'position_m':V,'normal_link':V,'pad':task_pad},('link','position_m','normal_link')),2),maxItems=2),
                'payload_mass_kg':P,'normal_force_per_finger_n':P,'friction_coefficient':nonnegative,'slip_safety_factor':{'type':'number','minimum':1},
                'acceleration_along_gravity_m_s2':nonnegative,'gravity_m_s2':V,'components':defs['robot']['properties']['components'],
                'required_components':arr(S),'conditions':defs['robot']['properties']['conditions'],'grasp_conditions':defs['grasp']['properties']['conditions'],
                'effort_safety_factor':{'type':'number','minimum':1},'additional_robot_loads':defs['robot']['properties']['loads'],
                'workpiece_load_names':dict(arr(S),uniqueItems=True),'grasp_model':enum('vertical_friction','finite_pad_wrench'),
                'pad_wrench_mode':enum('declared_per_pad','total_wrench'),'probes':arr(ref('robot_probe')),'actuation_reactions':arr(ref('actuation_reaction')),'notes':{},
                'force_measurement':obj({'measured_hold_interval_n':dict(arr(P,2),maxItems=2),'absolute_error_n':nonnegative,'error_verified':B,'holding_window_verified':B,'reference':S},('measured_hold_interval_n','absolute_error_n'))}
    task=header|obj(task_props,('task_id','model_path','poses','contacts','payload_mass_kg','normal_force_per_finger_n','friction_coefficient','slip_safety_factor'));task['$defs']=defs
    campaign=header|obj({'schema_version':{'const':'simplecae-campaign-1.0'},'title':S,'items':arr(obj({'id':{'type':'string','pattern':'^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$'},'case_path':S,'case_sha256':hash_value,'ledger_path':S},('id','case_path','case_sha256')),1),'notes':{}},('schema_version','title','items'))
    from .thermal_network import schema as thermal_schema
    case['oneOf'].append(thermal_schema())
    result['properties']['schema_version']['enum'].append('thermal-network-result-1.0')
    result['properties']['analysis']['enum'].append('thermal_network')
    from .thermal_solid import schema as solid_thermal_schema
    case['oneOf'].append(solid_thermal_schema())
    result['properties']['schema_version']['enum'].append('thermal-solid-result-1.0')
    result['properties']['analysis']['enum'].append('thermal_solid')
    from .modal import schema as modal_schema
    case['oneOf'].append(modal_schema())
    result['properties']['schema_version']['enum'].append('modal-solid-result-1.0')
    result['properties']['analysis']['enum'].append('modal')
    from .motion import schema as motion_schema
    case['oneOf'].append(motion_schema())
    result['properties']['schema_version']['enum'].append('motion-loads-result-1.0')
    result['properties']['analysis']['enum'].append('motion_loads')
    from .durability import schema as durability_schema
    for mode in ('fatigue', 'creep'):
        case['oneOf'].append(durability_schema(mode))
        result['properties']['schema_version']['enum'].append(mode+'-data-result-1.0')
        result['properties']['analysis']['enum'].append(mode+'_data')
    return {'case':case,'result':result,'signal':signal,'comparison':comparison,'evidence':ledger,'evidence-review':ledger_review,'interface':interface,'task-family':family,'gripper-task':task,'campaign':campaign}


def export_schemas(directory):
    from .case import write_json
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    for name,schema in contracts().items():write_json(directory/(name+'.schema.json'),schema)


class ContractError(ValueError):
    """Machine-readable input repair information; remains a ValueError for API callers."""
    def __init__(self, message, details):
        super().__init__(message)
        self.details = details


def check_contract(value,kind='case'):
    from jsonschema import Draft202012Validator
    schema=contracts()[kind]
    if kind == 'case' and isinstance(value, dict):
        # Derive the discriminator from the actual contract, not branch indices
        # that silently drift whenever a physics family is added or reordered.
        branches={}
        for option in schema['oneOf']:
            branch=option
            if '$ref' in branch:
                branch=schema
                for token in option['$ref'].split('/')[1:]:branch=branch[token]
            declaration=branch['properties']['schema_version']
            versions=declaration.get('enum', [declaration.get('const')])
            for version in versions:branches[version]=branch
        version=value.get('schema_version')
        if not isinstance(version,str) or version not in branches:
            details={'code':'unsupported_schema_version','path':'$.schema_version',
                     'supported_schema_versions':list(branches),'worker_started':False,
                     'next_action':'Select an applicable documented case contract, or retain an unsupported/information check in a task plan. Do not rename unsupported physics to a supported analysis.'}
            raise ContractError('JSON contract: $.schema_version: missing or unsupported schema version; supported: '+', '.join(branches),details)
        schema=branches[version] | {'$defs':schema['$defs']}
    validator=Draft202012Validator(schema);errors=sorted(validator.iter_errors(value),key=lambda e:list(map(str,e.path)))
    if errors:
        leaves=[]
        def descend(error):
            if error.context:
                for child in error.context:descend(child)
            else:leaves.append(error)
        for error in errors:descend(error)
        leaves=sorted(leaves,key=lambda e:(-len(e.absolute_path),str(list(e.absolute_path))))
        messages=[]
        for e in leaves:
            location='$'+''.join(f'[{x}]' if isinstance(x,int) else '.'+str(x) for x in e.absolute_path)
            message=location+': '+e.message
            if message not in messages:messages.append(message)
        raise ContractError('JSON contract: '+ '; '.join(messages[:4]),
            {'code':'invalid_contract','issues':messages,
             'next_action':'Repair the located input fields using the selected contract; preserve physical meaning and declared requirements.'})
    return value
