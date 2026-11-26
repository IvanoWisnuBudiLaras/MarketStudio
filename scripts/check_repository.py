"""Check the public MarketStudio repository without external dependencies."""

import argparse
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQUIRED_DOCUMENTS = (
    "AGENTS.md",
    "PROJECT_CONTEXT.md",
    "BRD.md",
    "GOALS.md",
    "ROADMAP.md",
    "TSD.md",
    "docs/DECISIONS.md",
)
SECRET_PATTERNS = {
    "private key": re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----"),
    "AWS access key ID": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "GitHub token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})\b"),
}
TEXT_SUFFIXES = {".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".ini",
                 ".py", ".js", ".mjs", ".ts", ".tsx", ".sh", ".sql"}


def validate_skill(path):
    text = path.read_text(encoding="utf-8")
    frontmatter = re.match(r"\A---\n(.*?)\n---(?:\n|$)", text, re.DOTALL)
    if not frontmatter:
        return "YAML frontmatter is missing"

    name = re.search(r"^name:[ \t]*([a-z0-9-]+)[ \t]*$", frontmatter[1], re.MULTILINE)
    if not name or name[1] != path.parent.name:
        return "skill name must match its directory"

    if not re.search(r"^description:[ \t]*\S", frontmatter[1], re.MULTILINE):
        return "skill description is missing"

    if not text[frontmatter.end():].strip():
        return "skill instructions are empty"

    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    root = parser.parse_args().root
    errors = []
    index_entries = subprocess.check_output(["git", "ls-files", "-z"], cwd=root)
    tracked = index_entries.decode().split("\0")
    for name in REQUIRED_DOCUMENTS:
        path = root / name
        if not path.is_file() or not path.read_text(encoding="utf-8").strip():
            errors.append(f"{name}: required document is missing or empty")

    ignored = subprocess.run(
        ["git", "check-ignore", "--no-index", "--stdin", "-z"],
        cwd=root,
        input=index_entries,
        capture_output=True,
        check=False,
    )
    if ignored.returncode not in (0, 1):
        raise RuntimeError("Could not check tracked files against ignore rules")
    errors.extend(
        f"{name}: tracked file matches .gitignore"
        for name in ignored.stdout.decode().split("\0") if name
    )

    for name in filter(None, tracked):
        path = root / name
        if path.is_symlink() or not path.is_file():
            continue
        if path.name == "SKILL.md" and name.startswith((".agents/skills/", "skills-drafts/")):
            issue = validate_skill(path)
            if issue:
                errors.append(f"{name}: {issue}")

        if path.suffix in TEXT_SUFFIXES or path.name.startswith(".env."):
            text = path.read_text(encoding="utf-8")
            for kind, pattern in SECRET_PATTERNS.items():
                if pattern.search(text):
                    errors.append(f"{name}: possible {kind}")

    if errors:
        print("\n".join(f"FAIL {error}" for error in errors))
        return 1
    print("PASS required documents, skill metadata, ignored paths and credential patterns")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
