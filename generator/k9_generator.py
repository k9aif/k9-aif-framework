# SPDX-License-Identifier: LicenseRef-K9AIF-Proprietary
# K9-AIF™

"""
K9-AIF Generator CLI

Usage:
    ./k9_generator.sh preview <AppName>
    ./k9_generator.sh run <AppName>
    ./k9_generator.sh recycle <AppName>
"""

import os
import re
import sys
import time
from pathlib import Path
from datetime import datetime
from jinja2 import Environment, FileSystemLoader


def print_banner(version: str = "v0.1.0"):
    print(f"\n=== K9-AIF Generator {version} ===")


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROJECTS_DIR = PROJECT_ROOT / "k9_projects"
PROJECTS_DIR.mkdir(parents=True, exist_ok=True)

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))


def to_snake_case(name: str) -> str:
    """Convert CamelCase or mixed name to snake_case"""
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def to_pascal_case(name: str) -> str:
    """Convert app name to PascalCase for class names."""
    snake = to_snake_case(name)
    return "".join(part.capitalize() for part in snake.split("_"))


def render_template(template_name: str, context: dict) -> str:
    template = env.get_template(template_name)
    return template.render(context)


def generator_preview(app_name: str, squad_name: str = "default_squad"):
    """Dry run: show what will be created."""
    app_folder = to_snake_case(app_name)
    app_dir = PROJECTS_DIR / app_folder

    print(f"\nPreview of files that will be generated for {app_name}")
    print(f"\n[PREVIEW] Application: {app_name}")
    print(f"[PREVIEW] Target folder: {app_dir}")
    print("[PREVIEW] Will create:")

    print(f"  {app_dir}/agents/")
    print(f"  {app_dir}/orchestrators/")
    print(f"  {app_dir}/config/")
    print(f"  {app_dir}/tests/")
    print(f"  {app_dir}/main.py")

    print(f"  {app_dir}/agents/retrieval_agent.py")
    print(f"  {app_dir}/agents/enrichment_agent.py")
    print(f"  {app_dir}/agents/summarizer_agent.py")

    print(f"  {app_dir}/orchestrators/default_orchestrator.py")

    print(f"  {app_dir}/config/config.yaml")
    print(f"  {app_dir}/config/squads.yaml")
    print(f"  {app_dir}/config/agents.yaml")

    print(f"  {app_dir}/tests/test_{app_folder}.py")
    print(f"  {app_dir}/tests/conftest.py")

    print(f"\n --- Done! ---")


def generator_run(
    app_name: str,
    squad_name: str = "default_squad",
    default_intent: str = "generic",
    query: str = "Sample query"
):
    """Generate runnable K9-AIF application scaffold."""

    app_folder = to_snake_case(app_name)
    app_class_prefix = to_pascal_case(app_name)

    app_dir = PROJECTS_DIR / app_folder
    agents_dir = app_dir / "agents"
    orch_dir = app_dir / "orchestrators"
    config_dir = app_dir / "config"
    tests_dir = app_dir / "tests"

    print("\n[INFO] Working...")
    time.sleep(0.5)

    for d in (agents_dir, orch_dir, config_dir, tests_dir):
        print(f"[INFO] Creating folder: {d}")
        d.mkdir(parents=True, exist_ok=True)
        time.sleep(0.2)

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    orchestrator_class = f"{app_class_prefix}Orchestrator"

    agents = [
        {"file": "retrieval_agent", "class": f"{app_class_prefix}RetrievalAgent", "id": "retrieval_agent"},
        {"file": "enrichment_agent", "class": f"{app_class_prefix}EnrichmentAgent", "id": "enrichment_agent"},
        {"file": "summarizer_agent", "class": f"{app_class_prefix}SummarizerAgent", "id": "summarizer_agent"},
    ]

    print("[INFO] Generating agents...")
    for agent in agents:
        code = render_template(
            "agent_template.py.j2",
            {
                "class_name": agent["class"],
                "timestamp": timestamp,
            }
        )
        path = agents_dir / f"{agent['file']}.py"
        print(f"[INFO] Writing file: {path}")
        path.write_text(code + "\n", encoding="utf-8")
        time.sleep(0.1)

    print("[INFO] Generating orchestrator...")
    orch_code = render_template(
        "orchestrator_template.py.j2",
        {
            "app_name": app_class_prefix,
            "orchestrator_class": orchestrator_class,
            "flow_name": squad_name,
            "timestamp": timestamp,
        }
    )
    orch_path = orch_dir / "default_orchestrator.py"
    print(f"[INFO] Writing file: {orch_path}")
    orch_path.write_text(orch_code + "\n", encoding="utf-8")

    print("[INFO] Generating config.yaml, squads.yaml, and agents.yaml...")

    config_yaml = render_template(
        "config_template.yaml.j2",
        {
            "app_name": app_class_prefix,
            "app_folder": app_folder,
            "squad_name": squad_name,
            "default_intent": default_intent,
            "query": query,
            "timestamp": timestamp,
        }
    )
    (config_dir / "config.yaml").write_text(config_yaml + "\n", encoding="utf-8")

    squads_yaml = render_template(
        "squads_template.yaml.j2",
        {
            "app_name": app_class_prefix,
            "app_folder": app_folder,
            "squad_name": squad_name,
            "orchestrator_class": orchestrator_class,
            "agents": agents,
            "timestamp": timestamp,
        }
    )
    (config_dir / "squads.yaml").write_text(squads_yaml + "\n", encoding="utf-8")

    agents_yaml = render_template(
        "agents_template.yaml.j2",
        {
            "app_name": app_class_prefix,
            "app_folder": app_folder,
            "agents": agents,
            "timestamp": timestamp,
        }
    )
    (config_dir / "agents.yaml").write_text(agents_yaml + "\n", encoding="utf-8")

    print("[INFO] Generating main.py...")
    main_code = render_template(
        "main_template.py.j2",
        {
            "app_name": app_class_prefix,
            "app_folder": app_folder,
            "flow_name": squad_name,
            "orchestrator_class": orchestrator_class,
            "timestamp": timestamp,
        }
    )
    (app_dir / "main.py").write_text(main_code + "\n", encoding="utf-8")

    print(f"[INFO] Generating tests/test_{app_folder}.py...")
    test_code = render_template(
        "test_template.py.j2",
        {
            "app_name": app_class_prefix,
            "app_folder": app_folder,
            "flow_name": "default",
            "orchestrator_class": orchestrator_class,
            "timestamp": timestamp,
        }
    )
    (tests_dir / f"test_{app_folder}.py").write_text(test_code + "\n", encoding="utf-8")

    print("[INFO] Generating tests/conftest.py...")
    conftest_code = render_template(
        "conftest_template.py.j2",
        {"timestamp": timestamp},
    )
    (tests_dir / "conftest.py").write_text(conftest_code + "\n", encoding="utf-8")

    for d in (app_dir, agents_dir, orch_dir, config_dir, tests_dir):
        init_file = d / "__init__.py"
        if not init_file.exists():
            init_code = render_template(
                "init_template.py.j2",
                {"timestamp": timestamp}
            )
            init_file.write_text(init_code + "\n", encoding="utf-8")
            print(f"[INFO] Writing file: {init_file}")

    print("\n[INFO] Generated file tree:")
    for root, dirs, files in os.walk(app_dir):
        dirs.sort()
        files.sort()
        level = root.replace(str(app_dir), "").count(os.sep)
        indent = " " * 2 * level
        print(f"{indent}{Path(root).name}/")
        subindent = " " * 2 * (level + 1)
        for f in files:
            print(f"{subindent}{f}")

    print(f"\n[K9-AIF] Application {app_name} generated successfully!\n")
    print("Next steps:")
    print(f"cd k9_projects/{app_folder}")
    print("python main.py\n")
    print("Ready to Rumble!")


def recycle_app(app_name: str):
    """Move an app into k9_recycle_bin instead of deleting it."""
    app_folder = to_snake_case(app_name)
    app_dir = PROJECTS_DIR / app_folder

    if not app_dir.exists():
        print(f"[ERROR] App {app_name} not found at {app_dir}")
        return

    recycle_dir = PROJECT_ROOT / "k9_recycle_bin"
    recycle_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = recycle_dir / f"{app_folder}_{timestamp}"

    app_dir.rename(target)

    print(f"[INFO] App {app_name} moved to k9_recycle_bin at {target}")


def usage():
    print("""
K9-AIF Generator CLI

Usage:
  ./k9_generator.sh preview <AppName>
  ./k9_generator.sh run <AppName>
  ./k9_generator.sh recycle <AppName>

Examples:
  ./k9_generator.sh preview WeatherAssist
  ./k9_generator.sh run ACMEInsurance
  ./k9_generator.sh recycle PetStore
""")


if __name__ == "__main__":
    print_banner("v0.1.0")

    if len(sys.argv) < 3:
        usage()
        sys.exit(1)

    command = sys.argv[1].lower()
    app_name = sys.argv[2]

    app_folder = to_snake_case(app_name)
    app_dir = PROJECTS_DIR / app_folder

    match command:
        case "preview":
            if app_dir.exists():
                print(f"[ERROR] Target folder already exists: {app_dir}")
                print("[HINT] Delete or recycle it first, or use a different app name.\n")
                sys.exit(1)
            generator_preview(app_name)

        case "run":
            if app_dir.exists():
                print(f"[ERROR] Target folder already exists: {app_dir}")
                print("[HINT] Delete or recycle it first, or use a different app name.\n")
                sys.exit(1)
            generator_run(app_name)

        case "recycle":
            recycle_app(app_name)
            print(f"\n[K9-AIF] Application {app_name} recycled successfully!\n")

        case _:
            usage()
            sys.exit(1)