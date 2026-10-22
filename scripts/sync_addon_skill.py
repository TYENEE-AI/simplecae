"""Mirror agent documentation for the SimpleCADAPI addon; no runtime/cache copy."""
from pathlib import Path
import argparse
import shutil


def sync(root,check=False):
    root=Path(root).resolve(); target=root/'skill'
    sources=[root/'SKILL.md',root/'README.md',root/'README.en.md']
    for folder in ('references','assets','examples'):
        sources += [p for p in (root/folder).rglob('*') if p.is_file() and
                    not any(x in ('__pycache__','__marimo__','.pytest_cache') for x in p.parts)]
    stale=[]
    for source in sources:
        destination=target/source.relative_to(root)
        if not destination.is_file() or destination.read_bytes()!=source.read_bytes():
            stale.append(str(destination.relative_to(root)))
            if not check:
                destination.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(source,destination)
    if check and stale:raise ValueError('Addon skill mirror is stale: '+', '.join(stale[:10]))
    return len(sources)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--check',action='store_true')
    args=p.parse_args();print(sync(Path(__file__).resolve().parents[1],args.check))
