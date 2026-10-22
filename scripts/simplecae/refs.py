"""Map canonical Viewer refs across isolated CAD/CAE runtimes by exact evidence."""
from pathlib import Path
import json
import os
import subprocess
import sys
import numpy as np
from .case import sha256,write_json
from .diagnostics import WorkflowError


def resolve(reference, out, *, expected_sha256, cad_python=None, timeout=3000):
    prefix,sep,fragment=reference.rpartition('#')
    if not sep or not prefix or not fragment:
        raise ValueError('refs resolve requires a saved STEP path plus #canonical-face-reference')
    model=Path(prefix.strip('"')).expanduser().resolve();out=Path(out).resolve()
    if model.suffix.lower() not in ('.step','.stp') or not model.is_file():raise ValueError('Reference must name an existing STEP/STP')
    if sha256(model)!=expected_sha256:raise ValueError('STEP hash changed; reopen the Viewer and reselect this revision')
    runtime=cad_python or os.environ.get('SIMPLECAE_CADGEN_PY')
    if not runtime:
        raise WorkflowError('Set --cad-python or SIMPLECAE_CADGEN_PY to the separate cadgen Python; SimpleCAE does not import OCP.',
                            'cadgen_runtime_required',fields=['cad_python'],next_action='select_isolated_cadgen_runtime')
    from .defaults import MAX_WAIT_SECONDS
    if not isinstance(timeout,(int,float)) or isinstance(timeout,bool) or not 0<timeout<=MAX_WAIT_SECONDS:
        raise ValueError('timeout must be finite, positive and within the platform wait range')
    native=out.with_name(out.name+'.native.json')
    log=out.with_name(out.name+'.native.log')
    if any(p.exists() for p in (out,native,log)):raise ValueError('Reference output and native evidence must be fresh')
    out.parent.mkdir(parents=True,exist_ok=True)
    script=Path(__file__).resolve().parents[1]/'cadgen_face_signature.py'
    with log.open('x',encoding='utf-8') as stream:
        try:run=subprocess.run([str(runtime),str(script),str(model),'#'+fragment,'--expected-sha256',expected_sha256,'--out',str(native)],
                               stdout=stream,stderr=subprocess.STDOUT,timeout=timeout,check=False)
        except subprocess.TimeoutExpired as exc:
            raise WorkflowError('Native reference extraction timed out; retain its log and use the remaining task budget.',
                'cadgen_reference_timeout',next_action='inspect_native_reference_log',details={'log':str(log)}) from exc
    if run.returncode:
        raise WorkflowError('Native cadgen reference extraction failed; inspect the retained log. No face mapping accepted.',
            'cadgen_reference_failed',next_action='inspect_native_reference_log',details={'log':str(log),'returncode':run.returncode})
    record=json.loads(native.read_text(encoding='utf-8'))
    if record.get('geometry_sha256')!=expected_sha256 or sha256(model)!=expected_sha256:
        raise ValueError('STEP/native signature changed during mapping; reopen and reselect')
    from .geometry import session,inventory
    from .bridge import _resolve_v2
    with session(model) as g:
        body=record['body'];candidates=[]
        for _,tag in g.model.getEntities(3):
            volume=g.model.occ.getMass(3,tag);center=g.model.occ.getCenterOfMass(3,tag)
            bounds=g.model.getBoundingBox(3,tag)
            if (abs(volume-body['volume_mm3'])<=max(1e-6,abs(volume)*1e-5) and
                np.linalg.norm(np.asarray(center)-body['centroid_mm'])<=1e-3 and
                np.allclose(bounds,body['bbox_mm'],rtol=0,atol=1e-3)):
                candidates.append(tag)
    if len(candidates)!=1:
        raise WorkflowError('Viewer occurrence signature does not identify exactly one STEP solid; coincident occurrences need explicit native occurrence evidence.',
            'ambiguous_occurrence_signature',next_action='review_occurrence',details={'candidate_solid_ids':candidates})
    solid_id=candidates[0]
    with session(model,{'path':str(model),'solid_id':{'id':solid_id,'geometry_sha256':expected_sha256}}) as g:
        info=inventory(g,model)
    manifest={'schema':'simplecae.interface_manifold/2','frame':'world','part':{'solid_id':solid_id},
              'provenance':{'generator':'cadgen','generator_version':record['generator_version'],
                            'definition_id':record['occurrence'],'revision':expected_sha256,'content_hash':expected_sha256},
              'regions':{'selected':{'face_count':1,'faces':[record['face']]}}}
    binding=_resolve_v2(manifest,info)
    if sha256(model)!=expected_sha256:raise ValueError('STEP changed during mapping')
    result={'geometry_sha256':expected_sha256,'reference':reference,'canonical_reference':record['canonical_reference'],
            'solid_id':solid_id,'face_id':binding['regions']['selected'][0],
            'model':{'path':str(model),'solid_id':{'id':solid_id,'geometry_sha256':expected_sha256}},
            'selector':{'type':'face_ids','ids':binding['regions']['selected'],'geometry_sha256':expected_sha256},
            'native_evidence':str(native),'native_evidence_sha256':sha256(native),'binding':binding,
            'scope':'Current source-bound face mapping only; load direction/magnitude and physical interpretation remain caller inputs.'}
    write_json(out,result);return result
