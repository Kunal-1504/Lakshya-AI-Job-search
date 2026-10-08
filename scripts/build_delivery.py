"""Build a complete ordered source listing and a ZIP containing only deliverable files."""

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_DIRS = {
    ".git",
    ".vercel",
    ".agents",
    ".venv",
    "node_modules",
    "dist",
    "build",
    "data",
    "output",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "coverage",
}
HISTORICAL_PREVIEWS = {"dashboard-preview.jpg", "review-preview.jpg", "phase1-preview.jpg"}


def sources() -> list[Path]:
    result = []
    for path in ROOT.rglob("*"):
        relative = path.relative_to(ROOT)
        if not path.is_file() or any(
            part in EXCLUDED_DIRS or part.endswith(".egg-info") for part in relative.parts
        ):
            continue
        if path.name == "skills-lock.json":
            continue
        if (path.name.startswith(".env") and path.name != ".env.example") or path.name.endswith(
            (".pyc", ".tsbuildinfo", ".sqlite3")
        ):
            continue
        if path.parent.name == "docs" and path.name in HISTORICAL_PREVIEWS:
            continue
        if relative.as_posix() == "docs/SOURCE.md":
            continue
        result.append(path)
    return sorted(result, key=lambda path: path.relative_to(ROOT).as_posix())


def tree(files: list[Path]) -> str:
    entries: dict = {}
    for path in files:
        current = entries
        for part in path.relative_to(ROOT).parts:
            current = current.setdefault(part, {})
    lines = ["lakshya/"]

    def walk(children: dict, prefix: str) -> None:
        for index, (name, descendants) in enumerate(sorted(children.items())):
            last = index == len(children) - 1
            lines.append(
                prefix + ("└── " if last else "├── ") + name + ("/" if descendants else "")
            )
            if descendants:
                walk(descendants, prefix + ("    " if last else "│   "))

    walk(entries, "")
    return "\n".join(lines)


def main() -> None:
    files = sources()
    extensions = {
        ".py": "python",
        ".json": "json",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".tsx": "tsx",
        ".ts": "typescript",
        ".js": "javascript",
        ".css": "css",
        ".html": "html",
        ".toml": "toml",
        ".md": "markdown",
    }
    sections = [
        "# Lakshya — complete source\n\n"
        "This generated listing contains every deliverable source/configuration/test file in order, "
        "including the dependency lockfile. Runtime data and dependency directories are excluded.\n\n"
        "## Folder tree\n\n```text\n" + tree(files) + "\n```\n"
    ]
    for path in files:
        if path.suffix in {".jpg", ".jpeg", ".png"}:
            relative = path.relative_to(ROOT).as_posix()
            sections.append(f"\n## {relative}\n\n![Verified preview]({path.name})\n")
            continue
        text = path.read_text(encoding="utf-8")
        fence = "````" if "```" in text else "```"
        relative = path.relative_to(ROOT).as_posix()
        sections.append(
            f"\n## {relative}\n\n{fence}{extensions.get(path.suffix, 'text')}\n{text}\n{fence}\n"
        )
    document = ROOT / "docs/SOURCE.md"
    document.write_text("\n".join(sections), encoding="utf-8")
    archive = ROOT.parent / "lakshya-complete.zip"
    with ZipFile(archive, "w", ZIP_DEFLATED) as output:
        for path in files + [document]:
            output.write(path, "lakshya/" + path.relative_to(ROOT).as_posix())
    print(f"{len(files)} files listed: {document}")
    print(f"Archive: {archive}")


if __name__ == "__main__":
    main()
