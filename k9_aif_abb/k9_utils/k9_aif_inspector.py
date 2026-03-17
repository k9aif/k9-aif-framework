# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

"""
K9-AIF Inspector
Scans SBB applications to ensure compliance with ABB/SBB conventions.
"""

import ast
from pathlib import Path
from k9_aif_abb.k9_utils.k9_ascii import print_success, print_failure


BASE_DIR = Path(__file__).resolve().parent
APP_DIR = BASE_DIR / "k9_aif_apps"


def inspect_app(app_name: str):
    issues = []
    app_dir = APP_DIR / app_name

    if not app_dir.exists():
        issues.append(f"Application {app_name} not found under {APP_DIR}")
        return issues

    # 1. Config checks
    config_path = app_dir / "config/config.yaml"
    if not config_path.exists():
        issues.append("Missing config/config.yaml")

    # 2. Main.py checks
    main_path = app_dir / "main.py"
    if not main_path.exists():
        issues.append("Missing main.py")
    else:
        src = main_path.read_text()
        try:
            ast.parse(src)  # validate Python syntax
        except SyntaxError as e:
            issues.append(f"main.py has syntax error: {e}")
        if "load_app_config" not in src:
            issues.append("main.py does not call load_app_config()")
        if "setup_logging" not in src:
            issues.append("main.py does not call setup_logging()")

    # 3. Agent inheritance checks
    agents_dir = app_dir / "agents"
    if agents_dir.exists():
        for f in agents_dir.glob("*.py"):
            src = f.read_text()
            if "BaseAgent" not in src:
                issues.append(f"{f.name} does not subclass BaseAgent")

    # 4. Orchestrator inheritance checks
    orch_dir = app_dir / "orchestrators"
    if orch_dir.exists():
        for f in orch_dir.glob("*.py"):
            src = f.read_text()
            if "BaseOrchestrator" not in src:
                issues.append(f"{f.name} does not subclass BaseOrchestrator")

    return issues


def run_inspector():
    print("[K9-AIF Inspector] Scanning applications...")

    app_count = 0
    issue_count = 0
    all_issues = False

    for app in APP_DIR.iterdir():
        if app.is_dir():
            app_name = app.name
            app_count += 1
            print(f"\nInspecting application: {app_name}")
            issues = inspect_app(app_name)
            if not issues:
                print("All good!")
            else:
                all_issues = True
                issue_count += len(issues)
                for issue in issues:
                    print(f"{issue}")

    print("\n[K9-AIF Inspector] Scan complete.")
    print(f"[SUMMARY] {app_count} application(s) scanned, {issue_count} issue(s) found.")

    if not all_issues:
        print_success("All applications")
    else:
        print_failure("Inspector")


if __name__ == "__main__":
    run_inspector()