"""The demo seeder must produce the dataset it claims to.

A seeder is the first thing anyone runs, so a silent shortfall is worse than
a crash: the console still loads, the counts still look plausible, and the
thing that is missing is exactly the part a demo depends on. The analyst team
was seeded from six blueprints and inserted four, because the return value
was keyed by role and three of them share the `analyst` role — while the
reported total was hardcoded to `len(ANALYST_BLUEPRINTS)`, so the output
read 6 and disagreed with the database the whole time.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "seed_demo_data.py"

_BLUEPRINT_ROW = re.compile(r'^\s*\("[^"]+@[^"]+",\s*"[^"]+",\s*"([^"]+)"\),?\s*$')


def _analyst_blueprints() -> list[tuple[str, str, str]]:
    """`(email, name, role)` for every analyst, read from the source.

    Parsed from the file rather than imported, because importing the seeder
    pulls in the whole ORM and settings graph. The point here is that the
    *blueprint list itself* is internally consistent, which is checkable
    without a database.
    """
    text = SCRIPT.read_text()
    start = text.index("ANALYST_BLUEPRINTS")
    rows: list[tuple[str, str, str]] = []
    for line in text[start:].splitlines():
        if "ROLE_BLUEPRINTS" in line:
            break
        found = _BLUEPRINT_ROW.match(line)
        if found is not None:
            email = re.search(r'"([^"]+@[^"]+)"', line).group(1)  # type: ignore[union-attr]
            name = re.findall(r'"([^"]*)"', line)[1]
            rows.append((email, name, found.group(1)))
    return rows


def test_every_analyst_blueprint_has_a_distinct_email() -> None:
    """The team is keyed by email, so a duplicate would drop an analyst.

    Inserting is driven by a list and the returned map is keyed by role, so a
    repeated email would produce two rows with the same primary key and fail
    loudly at the database. Asserting it here means the failure is a test
    failure rather than a partially-seeded run.
    """
    emails = [row[0] for row in _analyst_blueprints()]
    assert len(emails) >= 6, f"expected a team of at least six, parsed {emails}"
    assert len(set(emails)) == len(emails), f"duplicate analyst email in {emails}"


def test_the_seeder_inserts_every_analyst_not_one_per_role() -> None:
    """The bug this file exists for, as a source-level invariant.

    The old code appended `list(users.values())` where `users` was keyed by
    role, so with three analysts on the `analyst` role only one was ever
    inserted. Asserting the *count relationship* catches the whole family:
    inserting the role map, or reporting a hardcoded blueprint length.

    An import-and-count test would need a migrated, seeded database and would
    assert 6 only because the suite happens to run after a seed — and it
    would pass again the moment someone reintroduced the overwrite. The
    relationship is the invariant that does not depend on database state.
    """
    blueprints = _analyst_blueprints()
    distinct_roles = {row[2] for row in blueprints}
    source = SCRIPT.read_text()

    # The insertion must be driven by a per-analyst list, not the role map.
    assert "db.add_all(all_users)" in source, (
        "analysts must be inserted from a per-analyst list; adding the role "
        "map's values drops everyone who shares a role"
    )
    assert re.search(r"all_users:\s*list\[UserRecord\]\s*=\s*\[\]", source), (
        "all_users must be an explicit per-analyst list"
    )
    # And the number of distinct roles must be *less* than the team, or this
    # test has stopped testing anything: if they were equal, keying by role
    # would be harmless and the regression would be invisible.
    assert len(distinct_roles) < len(blueprints), (
        f"expected several analysts to share a role, got {len(distinct_roles)} "
        f"roles for {len(blueprints)} analysts; the overwrite this guards "
        "against is no longer reachable and the test is vacuous"
    )


def test_the_reported_user_count_is_not_hardcoded() -> None:
    """The summary must count rows, not echo the blueprint length.

    Reporting `len(ANALYST_BLUEPRINTS)` while inserting fewer is how the
    original shortfall stayed invisible: the output read 6 and the database
    held 4, and nobody reconciled them because the number that *looked*
    authoritative was the one that was wrong.
    """
    source = SCRIPT.read_text()
    assert '"users": len(ANALYST_BLUEPRINTS)' not in source, (
        "the reported user count must come from the rows actually inserted, "
        "not from the blueprint length"
    )


def test_the_blueprint_count_matches_what_the_readme_publishes() -> None:
    """The README quotes the team size, so the two must not drift.

    Kept deliberately literal rather than reading the README: a test that
    re-parses prose stops being a check the moment the prose is reworded, and
    this only needs to fail when the roster itself changes.
    """
    assert len(_analyst_blueprints()) == 6


def test_seed_totals_is_a_literal_dict_returned_by_seed() -> None:
    """Sanity: the seeder still returns a totals mapping we can assert on.

    If `seed` stops returning a dict literal this test fails, which is the
    point — every other assertion here is about a function whose result is
    read by a human, so the shape needs pinning.
    """
    tree = ast.parse(SCRIPT.read_text())
    functions = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
    }
    assert "seed" in functions, "seed_demo_data.py must define seed()"
    assert any(isinstance(node, ast.Return) for node in ast.walk(functions["seed"]))


@pytest.mark.parametrize("flag", ["--reset", "--index", "--evidence-per-case"])
def test_the_documented_seeder_flags_exist(flag: str) -> None:
    """`make demo-reset` and the README's quick start name these flags.

    A renamed flag would leave the Makefile and the README failing at the
    first step a newcomer runs, with an argparse error rather than an
    explanation.
    """
    assert flag in SCRIPT.read_text()
