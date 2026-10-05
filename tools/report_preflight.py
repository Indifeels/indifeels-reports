"""IndiFeels report contract validation.
Reads reports-manifest.json so report code can evolve without the scheduler silently
publishing an incompatible or partial build.

Examples:
  python3 tools/report_preflight.py --phase pre daily monthly
  python3 tools/report_preflight.py --phase post daily monthly
"""
import argparse, json, os, pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "reports-manifest.json"

def fail(msg):
    print("PRECHECK FAILED:", msg, file=sys.stderr)
    raise SystemExit(2)

def git_sha():
    try:
        return subprocess.check_output(
            ["git","rev-parse","HEAD"], cwd=ROOT, text=True
        ).strip()
    except Exception:
        return os.environ.get("GITHUB_SHA","unknown")

def load_manifest():
    if not MANIFEST.exists():
        fail("reports-manifest.json is missing")
    try:
        data=json.loads(MANIFEST.read_text())
    except Exception as e:
        fail(f"manifest is invalid JSON: {e}")
    if data.get("schema_version") != 1:
        fail("unsupported manifest schema_version")
    reports=data.get("reports")
    if not isinstance(reports,list) or not reports:
        fail("manifest has no reports")
    ids=[r.get("id") for r in reports]
    if None in ids or len(ids)!=len(set(ids)):
        fail("report ids must be present and unique")
    for r in reports:
        for path in r.get("outputs",[]):
            if not path.startswith("r/") or ".." in pathlib.PurePosixPath(path).parts:
                fail(f"unsafe output path for {r['id']}: {path}")
        for path in r.get("builders",[]):
            if path and not (ROOT/path).exists():
                fail(f"builder referenced by {r['id']} does not exist: {path}")
    return data

def write_runtime(data):
    sha=git_sha()
    env_path=os.environ.get("GITHUB_ENV")
    if env_path:
        with open(env_path,"a",encoding="utf-8") as f:
            f.write(f"REPORT_CODE_SHA={sha}\n")
            f.write(f"REPORT_MANIFEST_VERSION={data.get('manifest_version','unknown')}\n")
    return sha

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--phase",choices=["pre","post"],required=True)
    p.add_argument("reports",nargs="+")
    args=p.parse_args()

    data=load_manifest()
    by_id={r["id"]:r for r in data["reports"]}
    unknown=[rid for rid in args.reports if rid not in by_id]
    if unknown:
        fail("reports not registered in manifest: "+", ".join(unknown))

    if args.phase=="pre":
        missing=[]
        for rid in args.reports:
            for name in by_id[rid].get("required_env",[]):
                if not os.environ.get(name):
                    missing.append(f"{rid}:{name}")
        if missing:
            fail("required configuration missing: "+", ".join(missing))
    else:
        missing=[]
        for rid in args.reports:
            for rel in by_id[rid].get("outputs",[]):
                pth=ROOT/rel
                if not pth.exists() or pth.stat().st_size==0:
                    missing.append(rel)
        if missing:
            fail("expected output missing/empty: "+", ".join(missing))

    sha=write_runtime(data)
    print(f"report contract OK ({args.phase}); code={sha[:12]}; manifest={data.get('manifest_version')}")
    summary=os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary,"a",encoding="utf-8") as f:
            f.write(f"\n### Report contract: {args.phase} OK\n")
            f.write(f"- Code SHA: `{sha}`\n")
            f.write(f"- Manifest: `{data.get('manifest_version')}`\n")
            f.write(f"- Reports: {', '.join(args.reports)}\n")

if __name__=="__main__":
    main()
