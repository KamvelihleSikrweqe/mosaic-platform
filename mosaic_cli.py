"""Command-line tooling for validating and releasing MOSAIC manifests."""
import argparse
import json
import sys
from pathlib import Path

from mosaic_sdk import MosaicClient, MosaicError

COMPONENTS = {"heading", "text", "metric", "data-table", "data-form", "button"}
PAGE_TYPES = {"dashboard", "data-list", "data-form"}


def validate_manifest(manifest):
    errors = []
    if not isinstance(manifest, dict):
        return ["Manifest must be a JSON object"]
    if manifest.get("schemaVersion", "1.0") != "1.0":
        errors.append("schemaVersion must be 1.0")
    pages = manifest.get("pages", [])
    if not isinstance(pages, list) or len(pages) > 30:
        errors.append("pages must be an array containing at most 30 pages")
        return errors
    for p_index, page in enumerate(pages, 1):
        if not isinstance(page, dict) or page.get("type", "dashboard") not in PAGE_TYPES:
            errors.append(f"pages[{p_index - 1}] has an invalid page type")
            continue
        components = page.get("components", [])
        if not isinstance(components, list) or len(components) > 100:
            errors.append(f"pages[{p_index - 1}].components must contain at most 100 components")
            continue
        for c_index, component in enumerate(components):
            if not isinstance(component, dict) or component.get("type") not in COMPONENTS:
                errors.append(f"pages[{p_index - 1}].components[{c_index}] has an unsupported type")
            elif component.get("action") and (
                not isinstance(component["action"], dict)
                or component["action"].get("type") != "workflow.run"
            ):
                errors.append(f"pages[{p_index - 1}].components[{c_index}] uses an unsupported action")
    return errors


def main(argv=None):
    parser = argparse.ArgumentParser(prog="mosaic", description="Develop and release MOSAIC applications")
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate", help="Validate a local application manifest")
    validate.add_argument("file", type=Path)
    export = sub.add_parser("export", help="Export an application manifest from a workspace")
    export.add_argument("--app-id", required=True)
    export.add_argument("--output", type=Path, default=Path("mosaic-app.json"))
    push = sub.add_parser("push", help="Save a local manifest as the next application version")
    push.add_argument("--app-id", required=True)
    push.add_argument("--file", type=Path, required=True)
    release = sub.add_parser("release", help="Release the current application manifest to an environment")
    release.add_argument("--app-id", required=True)
    release.add_argument("--environment", choices=("development", "staging", "production"), required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            manifest = json.loads(args.file.read_text(encoding="utf-8"))
            errors = validate_manifest(manifest)
            if errors:
                for error in errors:
                    print("ERROR:", error)
                return 1
            print("Manifest is valid.")
            return 0
        client = MosaicClient()
        if args.command == "export":
            app = client.get_app(args.app_id)
            errors = validate_manifest(app.get("config") or {})
            if errors:
                raise MosaicError("Remote manifest is invalid: " + "; ".join(errors))
            args.output.write_text(json.dumps(app["config"], indent=2) + "\n", encoding="utf-8")
            print(f"Exported {app['name']} to {args.output}")
            return 0
        if args.command == "push":
            manifest = json.loads(args.file.read_text(encoding="utf-8"))
            errors = validate_manifest(manifest)
            if errors:
                raise MosaicError("Local manifest is invalid: " + "; ".join(errors))
            app = client.get_app(args.app_id)
            result = client.save_manifest(args.app_id, manifest, app["version"])
            print(f"Saved {result['name']} as version {result['version']}")
            return 0
        result = client.release(args.app_id, args.environment)
        print(f"Released {result['app_id']} as v{result['version']} to {result['environment']}")
        return 0
    except (OSError, ValueError, MosaicError) as exc:
        print(f"mosaic: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
