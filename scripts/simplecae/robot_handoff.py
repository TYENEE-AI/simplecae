"""Associate per-link STEP geometry without treating visual meshes as FEM."""
from pathlib import Path
from .case import sha256, write_json
from .robot import read_urdf


def link_steps(urdf, directory, out, *, links=None, package_roots=None, massless_links=()):
    out=Path(out).resolve()
    if out.exists():raise ValueError('Robot STEP association output must be fresh; retain previous evidence')
    robot=read_urdf(urdf,package_roots,massless_links)
    requested=links or [n for n in robot['links'] if n not in massless_links]
    if len(set(requested))!=len(requested) or set(requested)-set(robot['links']):raise ValueError('Requested FEM links must be unique known URDF link names')
    directory=Path(directory).resolve()
    if not directory.is_dir():raise ValueError('Per-link STEP directory does not exist: '+str(directory))
    out.mkdir(parents=True,exist_ok=False)
    result={};missing=[]
    for name in requested:
        candidates=[p for p in directory.iterdir() if p.is_file() and p.stem==name and p.suffix.lower() in ('.step','.stp')]
        if len(candidates)>1:raise ValueError(f'{name}: ambiguous STEP files; keep exactly one <link_name>.step/.stp')
        if not candidates:missing.append(name);continue
        path=candidates[0]
        before=sha256(path)
        from .geometry import inspect
        info=inspect(path,Path(out)/f'link-{len(result)}.geometry.json')
        if sha256(path)!=before:raise ValueError(f'{name}: STEP changed during association; rerun in a fresh output directory')
        mesh_assets=[a for a in robot['assets'] if a['link']==name]
        result[name]={'model':{'path':str(path),'expected_bbox_mm':info['bbox_mm']},
                      'step_sha256':before,'visual_meshes':mesh_assets,
                      'volume_mm3':info['volume_mm3'],'center_of_mass_mm':info['center_of_mass_mm'],
                      'step_analysis_units':'mm','step_rescale_applied':False,
                      'next_action':'Use this model in the link component case, select actual support/load ports and declare link_from_component. Robot component FEM checks sourced density against URDF mass and transforms the CAD COM into the link frame.'}
    if sha256(Path(urdf))!=robot['sha256']:raise ValueError('URDF changed during STEP association')
    report={'status':'needs_information' if missing else 'associated', 'models':result,
            'missing_link_steps':missing,'urdf_sha256':robot['sha256'],
            'whole_product_pass_available':False,'consistency_qualification':False,
            'meaning':'File association and native STEP dimensions only. URDF visual scale is retained as evidence, never reapplied to STEP. Frame/mass/COM consistency must pass component FEM; mesh rendering alone cannot establish it.'}
    write_json(Path(out)/'link-models.json',report);return report
