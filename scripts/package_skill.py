"""Build a portable source skill archive, excluding local binaries/environments/results."""
from pathlib import Path
import argparse
import json
import zipfile
import tomllib
from simplecae.release import check_qualification,check_development_snapshot,delivery_files,delivery_hashes


def main():
    root = Path(__file__).resolve().parents[1]
    version=tomllib.loads((root/'pyproject.toml').read_text(encoding='utf-8'))['project']['version']
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=root.parent / f"simplecae-{version}.zip")
    parser.add_argument('--development',action='store_true',help='Explicitly package development sources without claiming final release qualification')
    parser.add_argument('--public-preview',action='store_true',help='Qualified source-only preview; omit private validation history and embed a source-bound public summary')
    parser.add_argument('--public-release',action='store_true',help='Final source-only release with current audit, both platform workflows and Agent integration evidence')
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError("archive already exists; choose a new output filename")
    if sum((args.development,args.public_preview,args.public_release))>1:raise ValueError('choose exactly one distribution channel')
    public=args.public_preview or args.public_release
    receipt=None
    if public:
        from simplecae.public_preview import make_public_receipt
        receipt=make_public_receipt(root,version,channel='release' if args.public_release else 'developer-preview')
    elif args.development:
        check_development_snapshot(root,version)
    else:
        check_qualification(root,version)
    validation = root / "validation" / ("development-validation.json" if args.development else "standard-validation.json")
    if not public and not json.loads(validation.read_text(encoding="utf-8"))["passed"]:
        raise ValueError("cannot package without passed recorded standard validation")
    sources=delivery_files(root,include_validation=not public)
    snapshot=delivery_hashes(root,include_validation=not public)
    with zipfile.ZipFile(args.out, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for p in sorted(set(sources)):
            archive.write(p, "simplecae/" + p.relative_to(root).as_posix())
        if receipt is not None:
            name='public-release.json' if args.public_release else 'public-preview.json'
            archive.writestr('simplecae/validation/'+name,json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
    with zipfile.ZipFile(args.out) as archive:
        bad = archive.testzip()
        if bad:
            raise RuntimeError(f"archive integrity failure: {bad}")
        names = archive.namelist()
        if any("/.venv/" in n or "/.tools/" in n or "/outputs/" in n for n in names):
            raise RuntimeError("archive accidentally contains local runtime/results")
        import hashlib
        if any(hashlib.sha256(archive.read('simplecae/'+name)).hexdigest()!=value for name,value in snapshot.items()):
            raise RuntimeError('package contents differ from the source snapshot')
    if delivery_hashes(root,include_validation=not public)!=snapshot:raise RuntimeError('delivery changed during packaging')
    print(json.dumps({"archive": str(args.out.resolve()), "files": len(names), "bytes": args.out.stat().st_size,
                      "qualification":'public release' if args.public_release else 'public developer preview' if args.public_preview else 'development checkpoint' if args.development else 'release audit verified'}))


if __name__ == "__main__":
    main()
