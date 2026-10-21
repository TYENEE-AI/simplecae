"""Install qualified skill files with recoverable backup, preserving local runtime."""
from pathlib import Path
from datetime import datetime,timezone
import argparse,json,os,shutil,tomllib,uuid
from simplecae.release import check_qualification,check_development_snapshot,delivery_files,delivery_hashes
from simplecae.case import sha256,write_json


def default_skills_root(agent):
    home=Path.home()
    roots={
        'codex':Path(os.environ.get('CODEX_HOME',str(home/'.codex')))/'skills',
        'claude':Path(os.environ.get('CLAUDE_CONFIG_DIR',str(home/'.claude')))/'skills',
        'deepseek':home/'.agents/skills',
        'omp':home/'.omp/agent/skills',
        'pi':home/'.agents/skills',
    }
    return roots[agent]


def install(root,skills_root,backup_root,*,development=False):
    root=Path(root).expanduser().resolve();skills_root=Path(skills_root).expanduser().resolve();destination=skills_root/'simplecae'
    version=tomllib.loads((root/'pyproject.toml').read_text(encoding='utf-8'))['project']['version']
    qualify=check_development_snapshot if development else check_qualification
    qualify(root,version);source_hashes=delivery_hashes(root)
    if destination.resolve()==root or destination.resolve().is_relative_to(root):raise ValueError('installation target must be separate from the source skill')
    if destination.is_symlink():raise ValueError('installation target is a symlink; choose an explicit real skills directory')
    destination=destination.resolve();backup_root=Path(backup_root).resolve()
    if backup_root.is_relative_to(destination):raise ValueError('backup must be outside the installed skill')
    old_files=[p for p in delivery_files(destination) if p.is_file()] if destination.exists() else []
    old_hashes={p.relative_to(destination).as_posix():sha256(p) for p in old_files}
    backup=backup_root/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8])
    backup.mkdir(parents=True,exist_ok=False)
    for path in old_files:
        if not path.resolve().is_relative_to(destination):raise ValueError('managed installation file escapes target via symlink')
        relative=path.relative_to(destination);target=backup/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
        if sha256(target)!=old_hashes[relative.as_posix()]:raise RuntimeError('installed file changed during backup')
    write_json(backup/'installation-backup.json',{'target':str(destination),'files_sha256':old_hashes,
        'scope':'Managed skill source/resources/tests/validation only. Runtime, tools, outputs and unrelated root files remain in place.'})
    destination.mkdir(parents=True,exist_ok=True)
    # Every removal is a single backed-up file; no recursive delete or move.
    for relative in sorted(set(old_hashes)-set(source_hashes)):
        target=destination/relative
        if not target.resolve().is_relative_to(destination) or sha256(target)!=old_hashes[relative]:raise RuntimeError('stale installed file changed or escaped the intended skill')
        target.unlink()
    for relative,expected in source_hashes.items():
        source=root/relative;target=destination/relative
        if not target.resolve().is_relative_to(destination):raise ValueError('installation destination escapes target via symlink')
        if target.exists() and relative in old_hashes and sha256(target)!=old_hashes[relative]:raise RuntimeError('installed file changed after backup; refusing overwrite')
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
        if sha256(target)!=expected:raise RuntimeError('installed file differs from qualified source')
    if delivery_hashes(root)!=source_hashes:raise RuntimeError('qualified source changed during installation')
    qualify(destination,version)
    return {'installed':str(destination),'version':version,'backup':str(backup),'files':len(source_hashes),
            'qualification':'source-bound development checkpoint' if development else 'qualified release/preview',
            'runtime_action':'First installation: bootstrap in installed folder. Existing environment: pip install --no-deps -e installed folder to refresh version metadata. No hardware or external publishing.'}


def main():
    root=Path(__file__).resolve().parents[1]
    p=argparse.ArgumentParser()
    p.add_argument('--agent',choices=['codex','claude','deepseek','omp','pi'],default='codex',help='Standard local skill discovery directory; use --skills-root for custom profiles/project scope')
    p.add_argument('--skills-root',type=Path);p.add_argument('--backup-root',type=Path,default=root.parent/'simplecae-install-backups')
    p.add_argument('--show-target',action='store_true',help='Print the resolved destination without installing or changing files')
    p.add_argument('--development',action='store_true',help='Install a tested source-bound local development checkpoint, without release qualification');a=p.parse_args()
    skills_root=(a.skills_root or default_skills_root(a.agent)).expanduser().resolve()
    if a.show_target:
        print(json.dumps({'agent':a.agent,'target':str(skills_root/'simplecae'),'installed':False},ensure_ascii=True));return 0
    print(json.dumps(install(root,skills_root,a.backup_root,development=a.development),ensure_ascii=True));return 0


if __name__=='__main__':raise SystemExit(main())
