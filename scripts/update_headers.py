# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

from pathlib import Path

SKIP_DIRS = {
    ".git", ".venv", "venv", "__pycache__", ".pytest_cache",
    "build", "dist", ".mypy_cache", ".idea", ".vscode", "node_modules"
}

TARGET_HEADER = [
    "# SPDX-License-Identifier: Apache-2.0",
    "# K9-AIF Framework",
]

def should_skip(path: Path) -> bool:
    return any(part in SKIP_DIRS for part in path.parts)

def split_prefix(lines):
    prefix = []
    idx = 0

    if idx < len(lines) and lines[idx].startswith("#!"):
        prefix.append(lines[idx])
        idx += 1

    if idx < len(lines) and "coding" in lines[idx]:
        prefix.append(lines[idx])
        idx += 1

    return prefix, lines[idx:]

def strip_existing_header(lines):
    out = []
    i = 0

    while i < len(lines):
        line = lines[i]
        if line.startswith("# SPDX-License-Identifier:"):
            i += 1
            if i < len(lines) and lines[i].strip() == "# K9-AIF Framework":
                i += 1
            while i < len(lines) and lines[i].strip() == "":
                i += 1
            continue
        out.append(line)
        i += 1

    return out

def update_file(path: Path):
    original = path.read_text(encoding="utf-8")
    lines = original.splitlines()

    prefix, rest = split_prefix(lines)
    rest = strip_existing_header(rest)

    new_lines = []
    new_lines.extend(prefix)
    if prefix:
        new_lines.append("")
    new_lines.extend(TARGET_HEADER)
    new_lines.append("")
    new_lines.extend(rest)

    new_text = "\n".join(new_lines)
    if original.endswith("\n"):
        new_text += "\n"

    if new_text != original:
        path.write_text(new_text, encoding="utf-8")
        return True
    return False

def main():
    updated = 0
    for path in Path(".").rglob("*.py"):
        if should_skip(path):
            continue
        if update_file(path):
            updated += 1
            print(f"UPDATED {path}")
    print(f"\nDone. Updated {updated} files.")

if __name__ == "__main__":
    main()
