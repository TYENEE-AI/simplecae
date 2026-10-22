"""CAD labels are provenance, never mechanical property selection."""
from pathlib import Path
import json
from .case import sha256, number


def observations(case):
    bodies=case.get('bodies',[case])
    findings=[]
    for body in bodies:
        model=body.get('model',{})
        manifest=model.get('interface_manifest')
        if not manifest:continue
        data=json.loads(Path(manifest).read_text(encoding='utf-8-sig'))
        from .bridge import manifest_identity
        if manifest_identity(data)['model_sha256']!=sha256(Path(model['path'])):
            raise ValueError('CAD metadata belongs to a different STEP hash')
        p=data.get('provenance',{})
        if not any(k in p for k in ('cad_material_label','cad_density_kg_m3')):continue
        item={'kind':'cad_material_metadata','body':body.get('name','body'),
              'cad_material_label':p.get('cad_material_label'),
              'meaning':'CAD label is metadata only; mechanical properties come from the explicit sourced material record.',
              'warnings':[]}
        if 'cad_density_kg_m3' in p:
            cad=number(p['cad_density_kg_m3'],'CAD density',True)
            cae=body.get('material',{}).get('density_kg_m3')
            item.update(cad_density_kg_m3=cad,cae_density_kg_m3=cae)
            if cae is not None:
                difference=abs(cad-cae)/cae
                item['density_relative_difference']=difference
                if difference>.02:item['warnings'].append('CAD and analysis density differ by more than 2%; verify material and units. Analysis properties were not changed.')
        findings.append(item)
    return findings
