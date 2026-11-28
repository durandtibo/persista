r"""Check that the documentation refers to things that exist: the
relative links of the Markdown pages, their anchors, the reference page
of each user guide and the ``invoke`` tasks."""

from __future__ import annotations

import asyncio
import importlib.util
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs" / "docs"

PAGES = [ROOT / "README.md", *sorted(DOCS.rglob("*.md"))]
PAGE_PARAMS = [pytest.param(page, id=str(page.relative_to(ROOT))) for page in PAGES]
GUIDES = ["cache", "http", "record", "store", "testing"]

CODE_BLOCK = re.compile(r"^```.*?^```", re.MULTILINE | re.DOTALL)
# The target of a Markdown link, inline or of a reference definition.
LINK = re.compile(r"\]\(([^()\s]+)\)|^\[[^\]]+\]:\s+(\S+)", re.MULTILINE)
HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.MULTILINE)
# A task of invoke in a command, such as "inv test.unit".
TASK = re.compile(r"(?:^|`)inv ([a-z][\w.-]*)", re.MULTILINE)


def find_links(page: Path) -> list[str]:
    r"""Return the targets of the links of a page, without the ones of
    the web."""
    text = CODE_BLOCK.sub("", page.read_text(encoding="utf-8"))
    targets = (first or second for first, second in LINK.findall(text))
    return [target for target in targets if "://" not in target]


def find_anchors(page: Path) -> set[str]:
    r"""Return the anchors of the headings of a page, as MkDocs builds
    them."""
    text = CODE_BLOCK.sub("", page.read_text(encoding="utf-8"))
    anchors: set[str] = set()
    for heading in HEADING.findall(text):
        slug = re.sub(r"[^\w\s-]", "", heading.encode("ascii", "ignore").decode()).strip().lower()
        slug = re.sub(r"[-\s]+", "-", slug)
        anchor, index = slug, 0
        while anchor in anchors:
            index += 1
            anchor = f"{slug}_{index}"
        anchors.add(anchor)
    return anchors


def find_broken_links(page: Path) -> list[str]:
    r"""Return the links of a page whose file or anchor does not
    exist."""
    broken = []
    for link in find_links(page):
        path, _, anchor = link.partition("#")
        target = (page.parent / path).resolve() if path else page
        if not target.exists() or (
            anchor and target.suffix == ".md" and anchor not in find_anchors(target)
        ):
            broken.append(link)
    return broken


#########################
#     Documentation     #
#########################


@pytest.mark.parametrize("page", PAGE_PARAMS)
def test_relative_links_exist(page: Path) -> None:
    assert find_broken_links(page) == []


@pytest.mark.parametrize("name", GUIDES)
def test_user_guide_links_to_its_reference_page(name: str) -> None:
    assert f"../refs/{name}.md" in find_links(DOCS / "uguide" / f"{name}.md")


@pytest.mark.skipif(importlib.util.find_spec("invoke") is None, reason="Requires invoke")
async def test_documented_invoke_tasks_exist() -> None:
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "invoke",
        "--list",
        "--list-format=flat",
        cwd=ROOT,
        stdout=asyncio.subprocess.PIPE,
    )
    output, _ = await process.communicate()
    # A task is listed with its aliases, such as "check.all (check)".
    tasks = set(re.findall(r"^\s+([a-z][\w.-]*)", output.decode(), re.MULTILINE))
    tasks |= set(re.findall(r"^\s+[\w.-]+ \(([\w.-]+)\)", output.decode(), re.MULTILINE))
    documented = {task for page in PAGES for task in TASK.findall(page.read_text(encoding="utf-8"))}
    assert documented - tasks == set()
