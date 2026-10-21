"""Install local skill files with a recoverable backup, preserving local runtime."""
from pathlib import Path
from datetime import datetime,timezone
import argparse,json,os,shutil,tomllib,uuid
from simplecae.release import check_qualification,delivery_files
from simplecae.case import write_json


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


def install(root,skills_root,backup_root,*,development=False,verify_release=False):
    root=Path(root).expanduser().resolve();skills_root=Path(skills_root).expanduser().resolve();destination=skills_root/'simplecae'
    version=tomllib.loads((root/'pyproject.toml').read_text(encoding='utf-8'))['project']['version']
    # Release qualification is a maintainer action, not an installation prerequisite.
    # Keep --development as a compatibility alias for ordinary local installation.
    if development and verify_release:raise ValueError('choose ordinary development installation or --verify-release')
    for relative in ('SKILL.md','requirements-lock.txt','scripts/simplecae/cli.py'):
        if not (root/relative).is_file():raise ValueError(f'missing required skill file: {relative}')
    if verify_release:check_qualification(root,version)
    source_files={p.relative_to(root).as_posix():p for p in delivery_files(root) if p.is_file()}
    if destination.resolve().is_relative_to(root) or root.is_relative_to(destination.resolve()):raise ValueError('installation target must be separate from the source skill')
    if destination.is_symlink():raise ValueError('installation target is a symlink; choose an explicit real skills directory')
    destination=destination.resolve();backup_root=Path(backup_root).resolve()
    if backup_root.is_relative_to(destination):raise ValueError('backup must be outside the installed skill')
    old_files=[p for p in delivery_files(destination) if p.is_file()] if destination.exists() else []
    old_paths={p.relative_to(destination).as_posix():p for p in old_files}
    # Preflight every managed path before backup, removal or overwrite.
    for path in source_files.values():
        if not path.resolve().is_relative_to(root):raise ValueError('managed source file escapes source via symlink')
    for relative in set(source_files)|set(old_paths):
        target=destination/relative
        if not target.resolve().is_relative_to(destination):raise ValueError('managed installation file escapes target via symlink')
        if target.exists() and not target.is_file():raise ValueError(f'installation file conflicts with a directory: {relative}')
    backup=backup_root/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8])
    backup.mkdir(parents=True,exist_ok=False)
    for path in old_files:
        relative=path.relative_to(destination);target=backup/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
    write_json(backup/'installation-backup.json',{'target':str(destination),'files':sorted(old_paths),
        'scope':'Managed skill source/resources/tests/validation only. Runtime, tools, outputs and unrelated root files remain in place.'})
    destination.mkdir(parents=True,exist_ok=True)
    # Every removal is a single backed-up file; no recursive delete or move.
    for relative in sorted(set(old_paths)-set(source_files)):
        target=destination/relative
        if not target.resolve().is_relative_to(destination):raise ValueError('managed installation file escapes target via symlink')
        target.unlink()
    for relative,source in source_files.items():
        target=destination/relative
        if not target.resolve().is_relative_to(destination):raise ValueError('installation destination escapes target via symlink')
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
    return {'installed':str(destination),'version':version,'backup':str(backup),'files':len(source_files),
            'qualification':'source release verified' if verify_release else 'not requested (local installation)',
            'runtime_action':'New runtime: bootstrap once in the installed folder. Existing compatible runtime: call its Python with scripts/simplecae_cli.py directly. Metadata-only version differences do not require reinstalling dependencies.'}


def main():
    root=Path(__file__).resolve().parents[1]
    p=argparse.ArgumentParser()
    p.add_argument('--agent',choices=['codex','claude','deepseek','omp','pi'],default='codex',help='Standard local skill discovery directory; use --skills-root for custom profiles/project scope')
    p.add_argument('--skills-root',type=Path);p.add_argument('--backup-root',type=Path,default=root.parent/'simplecae-install-backups')
    p.add_argument('--show-target',action='store_true',help='Print the resolved destination without installing or changing files')
    mode=p.add_mutually_exclusive_group()
    mode.add_argument('--development',action='store_true',help='Compatibility alias for ordinary local installation; no validation receipt required')
    mode.add_argument('--verify-release',action='store_true',help='Optional maintainer audit: verify the source release receipt before installing')
    a=p.parse_args()
    skills_root=(a.skills_root or default_skills_root(a.agent)).expanduser().resolve()
    if a.show_target:
        print(json.dumps({'agent':a.agent,'target':str(skills_root/'simplecae'),'installed':False},ensure_ascii=True));return 0
    print(json.dumps(install(root,skills_root,a.backup_root,development=a.development,verify_release=a.verify_release),ensure_ascii=True));return 0


if __name__=='__main__':raise SystemExit(main())
