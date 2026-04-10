#!/usr/bin/env python3
"""
K9-AIF Semantic Graph Extractor (V2)

What it does:
1. Scans BOTH:
   - k9_aif_abb/
   - examples/
2. Builds the code graph:
   - Package, Module, Class
   - CONTAINS, EXTENDS
3. Builds the semantic architecture graph:
   - Component nodes for ABB / SBB / INFRA / CONFIG
   - semantic relationships like:
       ROUTES_TO
       PUBLISHES_TO
       DELIVERS_TO
       ORCHESTRATES
       CONTAINS
       REQUESTS_MODEL_ROUTING
       CREATES
       USES_FACTORY
       EMITS_TELEMETRY_TO
       PERSISTS_STATE_TO
       READS_FROM
       WRITES_TO
       LOADS
       READS_CONFIG_FROM
       DEFINES
       USES
       HOSTED_ON
4. Links semantic components back to code classes via:
   - IMPLEMENTED_BY

Usage:
    python extract_k9_graph.py

Output:
    k9_aif_graph.cypher
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Optional, Iterable


# -------------------------------------------------------------------
# Adjust this if needed
# -------------------------------------------------------------------
FRAMEWORK_ROOT = Path("~/ai/k9-aif-framework").expanduser().resolve()
SOURCE_ROOTS = [
    FRAMEWORK_ROOT / "k9_aif_abb",
    FRAMEWORK_ROOT / "examples",
]
OUTPUT_FILE = Path(__file__).parent / "k9_aif_graph.cypher"

WIPE_GRAPH_FIRST = True


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------
def esc(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace("'", "\\'")


def cypher_prop_str(d: dict) -> str:
    parts = []
    for k, v in d.items():
        if v is None:
            continue
        parts.append(f"{k}: '{esc(v)}'")
    return "{ " + ", ".join(parts) + " }"


def module_name_from_path(py_file: Path, root: Path) -> str:
    rel = py_file.relative_to(root)
    parts = list(rel.parts)

    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1][:-3]

    return ".".join(parts)


def package_name_from_module(module_name: str) -> str:
    if "." in module_name:
        return module_name.rsplit(".", 1)[0]
    return module_name


def get_base_name(base) -> Optional[str]:
    if isinstance(base, ast.Name):
        return base.id

    if isinstance(base, ast.Attribute):
        parts = []
        cur = base
        while isinstance(cur, ast.Attribute):
            parts.append(cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            parts.append(cur.id)
        return ".".join(reversed(parts))

    return None


def discover_python_files(root: Path) -> Iterable[Path]:
    if not root.exists():
        return []
    return [
        py_file
        for py_file in root.rglob("*.py")
        if "__pycache__" not in py_file.parts
    ]


def rel_to_framework(py_file: Path) -> str:
    return str(py_file.relative_to(FRAMEWORK_ROOT))


def top_example_name(py_file: Path) -> Optional[str]:
    """
    For files under examples/<app_name>/...
    return app_name
    """
    try:
        rel = py_file.relative_to(FRAMEWORK_ROOT / "examples")
    except ValueError:
        return None

    if not rel.parts:
        return None
    return rel.parts[0]


# -------------------------------------------------------------------
# Semantic classification
# -------------------------------------------------------------------
ROLE_RULES = {
    "BaseRouter": ("ABB", "Router", "Orchestration"),
    "BaseOrchestrator": ("ABB", "Orchestrator", "Orchestration"),
    "BaseSquad": ("ABB", "Squad", "Execution"),
    "BaseAgent": ("ABB", "Agent", "Execution"),
    "ModelRouterFactory": ("ABB", "Factory", "Inference"),
    "K9ModelRouter": ("ABB", "ModelRouter", "Inference"),
    "LLMFactory": ("ABB", "Factory", "Inference"),
    "MonitorServer": ("ABB", "Monitor", "Monitoring"),
    "PersistenceManager": ("ABB", "Persistence", "Persistence"),
    "SquadLoader": ("ABB", "Loader", "Execution"),
    "DefaultSquadMonitor": ("ABB", "Monitor", "Monitoring"),
}


def infer_semantic_component(
    class_name: str,
    fqname: str,
    module_name: str,
    py_file: Path,
) -> Optional[dict]:
    """
    Rule-based semantic classification for framework classes.
    """
    # Exact-name high confidence rules
    if class_name in ROLE_RULES:
        kind, role, layer = ROLE_RULES[class_name]
        return {
            "name": class_name,
            "kind": kind,
            "role": role,
            "layer": layer,
            "fqname": fqname,
            "module": module_name,
            "path": rel_to_framework(py_file),
        }

    # Heuristic ABB classification inside k9_aif_abb
    rel_path = rel_to_framework(py_file).lower()

    if "k9_aif_abb" in rel_path:
        role = None
        layer = None

        if "router" in class_name.lower():
            role = "Router"
            layer = "Orchestration"
        elif "orchestrator" in class_name.lower():
            role = "Orchestrator"
            layer = "Orchestration"
        elif "squad" in class_name.lower():
            role = "Squad"
            layer = "Execution"
        elif "agent" in class_name.lower():
            role = "Agent"
            layer = "Execution"
        elif "factory" in class_name.lower():
            role = "Factory"
            layer = "Inference"
        elif "monitor" in class_name.lower():
            role = "Monitor"
            layer = "Monitoring"
        elif "persist" in class_name.lower() or "storage" in class_name.lower():
            role = "Persistence"
            layer = "Persistence"

        if role:
            return {
                "name": class_name,
                "kind": "ABB",
                "role": role,
                "layer": layer,
                "fqname": fqname,
                "module": module_name,
                "path": rel_to_framework(py_file),
            }

    return None


def app_display_name(example_name: str) -> str:
    mapping = {
        "k9chat": "K9Chat",
        "acme_support_center": "ACMESupportCenter",
        "acmeinsuranceclaimsassist": "ACMEInsuranceClaimsAssist",
    }
    return mapping.get(example_name.lower(), example_name.replace("_", " ").title().replace(" ", ""))


# -------------------------------------------------------------------
# Emission helpers
# -------------------------------------------------------------------
def merge_node(lines: list[str], label: str, key_name: str, key_value: str, extra_props: dict | None = None):
    props = {key_name: key_value}
    if extra_props:
        props.update(extra_props)
    lines.append(f"MERGE (:{label} {cypher_prop_str(props)});")


def merge_component(lines: list[str], name: str, **props):
    merge_node(lines, "Component", "name", name, props)


def merge_match_rel(
    lines: list[str],
    from_label: str,
    from_key: str,
    from_value: str,
    rel_type: str,
    to_label: str,
    to_key: str,
    to_value: str,
):
    lines.append(
        f"MATCH (a:{from_label} {{{from_key}: '{esc(from_value)}'}}), "
        f"(b:{to_label} {{{to_key}: '{esc(to_value)}'}}) "
        f"MERGE (a)-[:{rel_type}]->(b);"
    )


# -------------------------------------------------------------------
# Main
# -------------------------------------------------------------------
def main():
    lines: list[str] = []
    seen_packages = set()
    seen_modules = set()
    seen_classes = set()
    seen_components = set()
    extends_edges = set()
    code_contains_edges = set()
    component_impl_edges = set()
    declared_example_apps = set()

    lines.append("// Auto-generated Cypher for K9-AIF semantic graph (V2)")
    if WIPE_GRAPH_FIRST:
        lines.append("MATCH (n) DETACH DELETE n;")
        lines.append("")

    # ---------------------------------------------------------------
    # Static semantic nodes for infra / config / distributed runtime
    # ---------------------------------------------------------------
    static_components = [
        {
            "name": "Redpanda",
            "kind": "INFRA",
            "role": "MessagingBroker",
            "layer": "Messaging",
        },
        {
            "name": "router_events",
            "kind": "INFRA",
            "role": "Topic",
            "layer": "Messaging",
        },
        {
            "name": "k9_storage",
            "kind": "INFRA",
            "role": "ObjectStorage",
            "layer": "Storage",
        },
        {
            "name": "input_bucket",
            "kind": "INFRA",
            "role": "Bucket",
            "layer": "Storage",
        },
        {
            "name": "artifact_bucket",
            "kind": "INFRA",
            "role": "Bucket",
            "layer": "Storage",
        },
        {
            "name": "squad.yaml",
            "kind": "CONFIG",
            "role": "SquadConfig",
            "layer": "Configuration",
        },
        {
            "name": "flows.yaml",
            "kind": "CONFIG",
            "role": "FlowConfig",
            "layer": "Configuration",
        },
    ]

    for comp in static_components:
        seen_components.add(comp["name"])
        merge_component(lines, comp["name"], **{k: v for k, v in comp.items() if k != "name"})

    # ---------------------------------------------------------------
    # Scan code roots
    # ---------------------------------------------------------------
    for root in SOURCE_ROOTS:
        for py_file in discover_python_files(root):
            module_name = module_name_from_path(py_file, root)
            if not module_name:
                continue

            package_name = package_name_from_module(module_name)
            short_module_name = module_name.split(".")[-1] if module_name else ""

            # Package node
            if package_name and package_name not in seen_packages:
                seen_packages.add(package_name)
                merge_node(lines, "Package", "name", package_name)

            # Module node
            fq_module_name = f"{root.name}.{module_name}" if root.name != "examples" else f"examples.{module_name}"
            if fq_module_name not in seen_modules:
                seen_modules.add(fq_module_name)
                merge_node(
                    lines,
                    "Module",
                    "name",
                    fq_module_name,
                    {
                        "short_name": short_module_name,
                        "path": rel_to_framework(py_file),
                        "root": root.name,
                    },
                )

            # Package contains module
            if package_name:
                edge = (package_name, fq_module_name)
                if edge not in code_contains_edges:
                    code_contains_edges.add(edge)
                    merge_match_rel(lines, "Package", "name", package_name, "CONTAINS", "Module", "name", fq_module_name)

            # Example app semantic node from examples/<app_name>/...
            example_name = top_example_name(py_file)
            if example_name and example_name not in declared_example_apps:
                declared_example_apps.add(example_name)
                app_name = app_display_name(example_name)
                if app_name not in seen_components:
                    seen_components.add(app_name)
                    merge_component(
                        lines,
                        app_name,
                        kind="SBB",
                        role="Application",
                        layer="Solution",
                        path=f"examples/{example_name}",
                    )

            # Parse AST
            try:
                tree = ast.parse(py_file.read_text(encoding="utf-8"))
            except Exception as e:
                print(f"Skipping {py_file}: {e}")
                continue

            for node in tree.body:
                if not isinstance(node, ast.ClassDef):
                    continue

                class_name = node.name
                fq_class_name = f"{fq_module_name}.{class_name}"

                # Class node
                if fq_class_name not in seen_classes:
                    seen_classes.add(fq_class_name)
                    merge_node(
                        lines,
                        "Class",
                        "fqname",
                        fq_class_name,
                        {
                            "name": class_name,
                            "module": fq_module_name,
                            "path": rel_to_framework(py_file),
                        },
                    )

                # Module contains Class
                edge = (fq_module_name, fq_class_name)
                if edge not in code_contains_edges:
                    code_contains_edges.add(edge)
                    merge_match_rel(lines, "Module", "name", fq_module_name, "CONTAINS", "Class", "fqname", fq_class_name)

                # EXTENDS edges
                for base in node.bases:
                    base_name = get_base_name(base)
                    if not base_name:
                        continue

                    edge = (fq_class_name, base_name)
                    if edge in extends_edges:
                        continue
                    extends_edges.add(edge)

                    lines.append(
                        f"MATCH (c:Class {{fqname: '{esc(fq_class_name)}'}}) "
                        f"MERGE (b:Class {{name: '{esc(base_name)}'}}) "
                        f"MERGE (c)-[:EXTENDS]->(b);"
                    )

                # Semantic classification for framework classes
                semantic = infer_semantic_component(
                    class_name=class_name,
                    fqname=fq_class_name,
                    module_name=fq_module_name,
                    py_file=py_file,
                )
                if semantic:
                    comp_name = semantic["name"]
                    if comp_name not in seen_components:
                        seen_components.add(comp_name)
                        merge_component(lines, comp_name, **{k: v for k, v in semantic.items() if k != "name"})

                    impl_edge = (comp_name, fq_class_name)
                    if impl_edge not in component_impl_edges:
                        component_impl_edges.add(impl_edge)
                        merge_match_rel(lines, "Component", "name", comp_name, "IMPLEMENTED_BY", "Class", "fqname", fq_class_name)

                # Example classes belong to SBB app
                if example_name:
                    app_name = app_display_name(example_name)
                    impl_edge = (app_name, fq_class_name)
                    if impl_edge not in component_impl_edges:
                        component_impl_edges.add(impl_edge)
                        merge_match_rel(lines, "Component", "name", app_name, "IMPLEMENTED_BY", "Class", "fqname", fq_class_name)

    # ---------------------------------------------------------------
    # Semantic architecture relationships
    # ---------------------------------------------------------------
    semantic_edges = [
        # Distributed router -> orchestrator path
        ("Component", "name", "BaseRouter", "PUBLISHES_TO", "Component", "name", "router_events"),
        ("Component", "name", "router_events", "HOSTED_ON", "Component", "name", "Redpanda"),
        ("Component", "name", "router_events", "DELIVERS_TO", "Component", "name", "BaseOrchestrator"),
        ("Component", "name", "BaseRouter", "WRITES_TO", "Component", "name", "k9_storage"),
        ("Component", "name", "BaseOrchestrator", "READS_FROM", "Component", "name", "k9_storage"),

        # Direct semantic backbone
        ("Component", "name", "BaseRouter", "ROUTES_TO", "Component", "name", "BaseOrchestrator"),
        ("Component", "name", "BaseOrchestrator", "ORCHESTRATES", "Component", "name", "BaseSquad"),
        ("Component", "name", "SquadLoader", "LOADS", "Component", "name", "BaseSquad"),
        ("Component", "name", "SquadLoader", "READS_CONFIG_FROM", "Component", "name", "squad.yaml"),
        ("Component", "name", "flows.yaml", "DEFINES", "Component", "name", "BaseOrchestrator"),
        ("Component", "name", "squad.yaml", "DEFINES", "Component", "name", "BaseSquad"),
        ("Component", "name", "BaseSquad", "CONTAINS", "Component", "name", "BaseAgent"),
        ("Component", "name", "BaseAgent", "REQUESTS_MODEL_ROUTING", "Component", "name", "ModelRouterFactory"),
        ("Component", "name", "ModelRouterFactory", "CREATES", "Component", "name", "K9ModelRouter"),
        ("Component", "name", "K9ModelRouter", "USES_FACTORY", "Component", "name", "LLMFactory"),

        # Monitoring / persistence / storage
        ("Component", "name", "BaseOrchestrator", "EMITS_TELEMETRY_TO", "Component", "name", "MonitorServer"),
        ("Component", "name", "BaseOrchestrator", "PERSISTS_STATE_TO", "Component", "name", "PersistenceManager"),
        ("Component", "name", "PersistenceManager", "USES", "Component", "name", "k9_storage"),
        ("Component", "name", "input_bucket", "HOSTED_ON", "Component", "name", "k9_storage"),
        ("Component", "name", "artifact_bucket", "HOSTED_ON", "Component", "name", "k9_storage"),
        ("Component", "name", "BaseOrchestrator", "READS_FROM", "Component", "name", "input_bucket"),
        ("Component", "name", "BaseOrchestrator", "WRITES_TO", "Component", "name", "artifact_bucket"),

        # Example apps use router
        ("Component", "name", "K9Chat", "USES", "Component", "name", "BaseRouter"),
        ("Component", "name", "ACMESupportCenter", "USES", "Component", "name", "BaseRouter"),
    ]

    for from_label, from_key, from_value, rel_type, to_label, to_key, to_value in semantic_edges:
        if from_value in seen_components and to_value in seen_components:
            merge_match_rel(lines, from_label, from_key, from_value, rel_type, to_label, to_key, to_value)

    # ---------------------------------------------------------------
    # Helpful indexes / constraints
    # ---------------------------------------------------------------
    lines.append("")
    lines.append("// Helpful indexes")
    lines.append("CREATE INDEX component_name_idx IF NOT EXISTS FOR (c:Component) ON (c.name);")
    lines.append("CREATE INDEX class_fqname_idx IF NOT EXISTS FOR (c:Class) ON (c.fqname);")
    lines.append("CREATE INDEX module_name_idx IF NOT EXISTS FOR (m:Module) ON (m.name);")
    lines.append("CREATE INDEX package_name_idx IF NOT EXISTS FOR (p:Package) ON (p.name);")

    OUTPUT_FILE.write_text("\n".join(lines), encoding="utf-8")
    print(f"Generated {OUTPUT_FILE}")


if __name__ == "__main__":
    main()