"""Read source-bound SimpleCAD occurrence metadata without importing a CAD kernel.

Only exact labelled occurrence chains are accepted. Unsupported or ambiguous
trees require explicit placement; geometry never supplies a guessed transform.
"""
import json
import re
from pathlib import Path
import numpy as np


def occurrence_placement(path, label, definition_id):
    components=(label or '').split('/')[2::2]
    if not components: return None
    text=Path(path).read_text(encoding='utf-8',errors='replace')
    pattern=r"DESCRIPTIVE_REPRESENTATION_ITEM\s*\(\s*'((?:[^']|'')*)'\s*,\s*'((?:[^']|'')*)'\s*\)"
    records=[]
    for name,payload in re.findall(pattern,text,re.S):
        if not name.startswith('SimpleCAD:occurrence:'): continue
        try:record=json.loads(payload.replace("''","'").replace('\r','').replace('\n',''))
        except json.JSONDecodeError: continue
        if record.get('record_kind')=='occurrence':records.append(record)
    chains=[[r] for r in records if r.get('component_id')==components[-1] and r.get('definition_id')==definition_id]
    for component in reversed(components[:-1]):
        chains=[[parent,*chain] for chain in chains for parent in records
                if parent.get('component_id')==component and parent.get('definition_id')==chain[0].get('parent_definition_id')]
    if len(chains)!=1: return None
    matrix=np.eye(4)
    try:
        for record in chains[0]:
            p=record['placement'];local=np.eye(4)
            local[:3,:3]=np.column_stack([p[k] for k in ('x_axis','y_axis','z_axis')])
            local[:3,3]=p['origin'];matrix=matrix@local
    except (KeyError,TypeError,ValueError): return None
    return {'source':'simplecad_step_occurrence_metadata','matrix_4x4':matrix.tolist(),
            'component_path':components,'definition_id':definition_id}


def assembly_tree_placement(path,label):
    """Resolve rigid AP242/AP214 placement chains using the STEPutils P21 DOM.

    Resolve product names AND occurrence names. Entity numbering/order never
    identifies a part. Unrecognised units/transformation types remain unresolved.
    """
    from steputils import p21
    segments=(label or '').split('/')[1:]
    if len(segments)<3 or len(segments)%2!=1:return None
    try:
        document=p21.readfile(str(path))
        entities={i.ref:({i.entity.name:i.entity.params} if p21.is_simple_entity_instance(i)
                         else {e.name:e.params for e in i.entities}) for i in document}
        def get(ref,name):return entities[ref][name]
        def product_name(definition):
            formation=get(definition,'PRODUCT_DEFINITION')[2]
            product=get(formation,'PRODUCT_DEFINITION_FORMATION')[2]
            return get(product,'PRODUCT')[1]
        def unit_scale(ref,seen=()):
            if ref in seen:raise ValueError('cyclic STEP unit')
            value=entities[ref]
            if 'LENGTH_UNIT' not in value:raise ValueError('not a length unit')
            if 'SI_UNIT' in value:
                prefix,unit=value['SI_UNIT']
                if str(unit)!='.METRE.':raise ValueError('unsupported STEP length unit')
                return {'$':1000.,'.MILLI.':1.,'.CENTI.':10.,'.DECI.':100.,'.MICRO.':.001,'.KILO.':1e6}[str(prefix)]
            conversion=value['CONVERSION_BASED_UNIT'][1]
            amount,base=get(conversion,'MEASURE_WITH_UNIT')
            return float(amount.param)*unit_scale(base,(*seen,ref))
        def representation_scale(ref):
            value=entities[ref]
            reps=[p for name,p in value.items() if name.endswith('SHAPE_REPRESENTATION')]
            if len(reps)!=1:raise ValueError('unsupported STEP representation')
            context=reps[0][-1];units=get(context,'GLOBAL_UNIT_ASSIGNED_CONTEXT')[0]
            lengths=[r for r in units if 'LENGTH_UNIT' in entities[r]]
            if len(lengths)!=1:raise ValueError('ambiguous length units')
            return unit_scale(lengths[0])
        def axis(ref,scale):
            p=get(ref,'AXIS2_PLACEMENT_3D');result=np.eye(4)
            origin=np.asarray(get(p[1],'CARTESIAN_POINT')[1],dtype=float)*scale
            z=np.asarray(get(p[2],'DIRECTION')[1] if str(p[2])!='$' else [0,0,1],dtype=float)
            x=np.asarray(get(p[3],'DIRECTION')[1] if str(p[3])!='$' else [1,0,0],dtype=float)
            z=z/np.linalg.norm(z);x=x-np.dot(x,z)*z;x=x/np.linalg.norm(x)
            result[:3,:3]=np.column_stack((x,np.cross(z,x),z));result[:3,3]=origin
            if not np.isfinite(result).all():raise ValueError('invalid STEP axes')
            return result
        transforms={}
        for value in entities.values():
            if 'CONTEXT_DEPENDENT_SHAPE_REPRESENTATION' not in value:continue
            relationship,shape=value['CONTEXT_DEPENDENT_SHAPE_REPRESENTATION']
            usage=get(shape,'PRODUCT_DEFINITION_SHAPE')[2]
            if 'NEXT_ASSEMBLY_USAGE_OCCURRENCE' not in entities.get(usage,{}):continue
            relation=entities[relationship]
            child_rep,parent_rep=relation['REPRESENTATION_RELATIONSHIP'][2:4]
            transform=relation['REPRESENTATION_RELATIONSHIP_WITH_TRANSFORMATION'][0]
            local_ref,parent_ref=get(transform,'ITEM_DEFINED_TRANSFORMATION')[2:4]
            matrix=axis(parent_ref,representation_scale(parent_rep))@np.linalg.inv(axis(local_ref,representation_scale(child_rep)))
            transforms.setdefault(usage,[]).append(matrix)
        occurrences={r:v['NEXT_ASSEMBLY_USAGE_OCCURRENCE'] for r,v in entities.items() if 'NEXT_ASSEMBLY_USAGE_OCCURRENCE' in v}
        chains=[(None,np.eye(4),[])]
        for i in range(1,len(segments),2):
            next_chains=[]
            for parent,matrix,refs in chains:
                for ref,occ in occurrences.items():
                    if ref in refs or len(transforms.get(ref,[]))!=1:continue
                    if (occ[1]==segments[i] and (parent is None or occ[3]==parent)
                        and product_name(occ[3])==segments[i-1] and product_name(occ[4])==segments[i+1]):
                        next_chains.append((occ[4],matrix@transforms[ref][0],[*refs,str(ref)]))
            chains=next_chains
        if len(chains)!=1:return None
        _,matrix,refs=chains[0]
        return {'source':'step_assembly_tree','matrix_4x4':matrix.tolist(),'occurrence_entities':refs,'label':label}
    except (ValueError,KeyError,IndexError,TypeError,p21.ParseError):
        return None
