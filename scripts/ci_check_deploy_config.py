"""Parse the deploy descriptors so a syntax error fails CI, not the deploy.

Neither render.yaml nor apps/frontend/vercel.json is executed by any test, so
nothing else would notice a typo until Render or Vercel tried to read it. This
only reads and checks; it never rewrites them.
"""

from __future__ import annotations

import json
import pathlib
import re
import sys
from typing import Any

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _fail(problems: list[str]) -> int:
    for problem in problems:
        print(f"[FAIL] {problem}", file=sys.stderr)
    return 1


#: Values Render must be able to read. A manifest that parses cleanly can
#: still be the wrong manifest: a `sync` flag typed as a YAML boolean rather
#: than the string Render expects means the variable is never prompted for,
#: and the deploy fails much later with a missing environment variable.
REQUIRED_SERVICE_KEYS = {"name", "runtime", "buildCommand", "startCommand", "healthCheckPath"}


def _is_prompted(env_var: dict[str, object]) -> bool:
    """True when Render will prompt for this value on deploy.

    `sync: false` parses as a YAML boolean. Render documents the string, and
    a boolean is not truthy-tested the same way, so both spellings are
    accepted here and the manifest is normalised to the string form.
    """
    value = env_var.get("sync")
    return value is False or str(value).lower() == "false"


def check_blueprint_prompts(service: dict[str, object]) -> list[str]:
    """A deploy needs at least one prompted variable, and it must be the database."""
    problems: list[str] = []
    env_vars = service.get("envVars")
    if not isinstance(env_vars, list) or not env_vars:
        return ["render.yaml declares no envVars; the service would deploy unconfigured"]
    prompted = [
        str(entry.get("key"))
        for entry in env_vars
        if isinstance(entry, dict) and _is_prompted(entry)
    ]
    if "AEGIS_DATABASE_URL" not in prompted:
        problems.append(
            "AEGIS_DATABASE_URL must be prompted for (sync: \"false\"); a hard-coded "
            "connection string in a committed manifest is a credential in git"
        )
    return problems


def check_render_yaml(problems: list[str]) -> None:
    path = ROOT / "render.yaml"
    try:
        document: Any = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        problems.append(f"render.yaml is not valid YAML: {exc}")
        return

    services = document.get("services") if isinstance(document, dict) else None
    if not isinstance(services, list) or not services:
        problems.append("render.yaml declares no services")
        return

    for service in services:
        name = service.get("name", "<unnamed>")
        for key in ("type", "runtime", "buildCommand", "startCommand", "healthCheckPath"):
            if not service.get(key):
                problems.append(f"render.yaml service {name!r} has no {key}")
        problems.extend(check_blueprint_prompts(service))
        # A command that names a script which does not exist deploys to a
        # service that dies on first boot, which is the worst place to find out.
        for key in ("buildCommand", "startCommand"):
            for script in re.findall(r"scripts/[A-Za-z0-9_./-]+", service.get(key) or ""):
                if not (ROOT / script).is_file():
                    problems.append(f"render.yaml service {name!r} invokes missing {script}")
    print(f"render.yaml: {len(services)} service(s) -> {[s.get('name') for s in services]}")


def check_vercel_json(problems: list[str]) -> None:
    path = ROOT / "apps" / "frontend" / "vercel.json"
    try:
        document: Any = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        problems.append(f"vercel.json is not valid JSON: {exc}")
        return

    for key in ("buildCommand", "outputDirectory", "rewrites"):
        if key not in document:
            problems.append(f"vercel.json is missing {key}")
    print(
        "vercel.json: buildCommand="
        f"{document.get('buildCommand')!r} outputDirectory={document.get('outputDirectory')!r}"
    )

    # The SPA rewrite target must be a real script, or Vercel serves a
    # directory listing for every client-side route.
    for script in ("build", "typecheck", "lint", "test"):
        package = json.loads((ROOT / "apps" / "frontend" / "package.json").read_text())
        if script not in package.get("scripts", {}):
            problems.append(f"vercel.json/CI expects an npm script {script!r} that does not exist")


def main() -> int:
    problems: list[str] = []
    check_render_yaml(problems)
    check_vercel_json(problems)
    if problems:
        return _fail(problems)
    print("deploy descriptors parsed cleanly")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
