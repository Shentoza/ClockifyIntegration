"""Sync the '## Changelog' section of a PR body into CHANGELOG.md's [Unreleased] block.

Reads the PR body from the PR_BODY environment variable.
Writes CHANGELOG.md in-place.  Exits 0 whether or not a change was made.
"""
from __future__ import annotations

import os
import re
import sys




def extract_changelog_section(pr_body: str) -> str | None:
    """Return the text under the '## Changelog' heading in the PR body, or None.

    HTML comments (template instructions) and empty bullet points left over
    from the template are stripped before returning.
    """
    # GitHub's web editor submits PR bodies with CRLF line endings; normalise
    # to LF so all regex anchors and string comparisons work uniformly.
    pr_body = pr_body.replace("\r\n", "\n").replace("\r", "\n")

    match = re.search(
        r"^## Changelog[ \t]*\n(.*?)(?=^## |\Z)",
        pr_body,
        re.MULTILINE | re.DOTALL,
    )
    if not match:
        return None

    section = match.group(1)

    # Strip HTML comments (<!-- ... -->) — these are template instructions
    section = re.sub(r"<!--.*?-->", "", section, flags=re.DOTALL)

    # Remove empty bullet points left from the template ("- " with nothing after)
    section = re.sub(r"^-[ \t]*$", "", section, flags=re.MULTILINE)

    # Remove ### subsections that have no content — only blank lines until
    # the next ### heading or end of string.
    section = re.sub(
        r"^### [^\n]+\n(?:[ \t]*\n)*(?=### |\Z)", "", section, flags=re.MULTILINE
    )

    # Strip trailing whitespace from each line
    lines = [line.rstrip() for line in section.splitlines()]

    # Drop leading and trailing blank lines
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()

    return "\n".join(lines) if lines else None


def replace_unreleased_block(changelog: str, new_content: str) -> str:
    """Replace the body of the [Unreleased] block with new_content.

    Walks the file line by line so version numbers and special characters
    in new_content are never misinterpreted as regex patterns.
    Raises RuntimeError if the [Unreleased] heading is not found.
    """
    lines = changelog.splitlines(keepends=True)
    result: list[str] = []
    in_unreleased = False
    found = False

    for line in lines:
        if line.rstrip() == "## [Unreleased]":
            in_unreleased = True
            found = True
            result.append(line)
            result.append("\n")
            result.append(new_content + "\n")
        elif in_unreleased:
            if line.startswith("## ["):
                in_unreleased = False
                result.append("\n")
                result.append(line)
            # else: skip old [Unreleased] content — it is replaced above
        else:
            result.append(line)

    if not found:
        raise RuntimeError(
            "'## [Unreleased]' heading not found in CHANGELOG.md — "
            "cannot sync PR changelog content."
        )

    return "".join(result)


def main() -> None:
    pr_body = os.environ.get("PR_BODY", "")

    new_content = extract_changelog_section(pr_body)
    if new_content is None:
        print("No '## Changelog' section found in PR body — skipping.")
        return
    if not new_content:
        print("Changelog section is empty after stripping — skipping.")
        return

    with open("CHANGELOG.md", encoding="utf-8") as f:
        original = f.read()

    try:
        updated = replace_unreleased_block(original, new_content)
    except RuntimeError as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)

    if updated == original:
        print("CHANGELOG.md is already up to date.")
        return

    with open("CHANGELOG.md", "w", encoding="utf-8") as f:
        f.write(updated)
    print("CHANGELOG.md updated.")


if __name__ == "__main__":
    main()
