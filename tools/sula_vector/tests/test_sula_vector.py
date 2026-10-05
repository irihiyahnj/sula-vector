"""Sula Vector v1.0 test suite (stdlib unittest only).

Covers:
- frontmatter parser (required/optional fields, lists, booleans, malformed)
- fragment loading (skip invalid, sort by time)
- views (digest, list, progress, family, thread, goals, principles, changes-summary)
- render --for-agent (principles prepended, byte-stable, principle-free recent activity)
- migrate.py (idempotence, kind assignment for change-records, releases, events)
- verifier-shell skill (closes goals, idempotent)
- scheduler skill (fires when due, silent when not)
- llm-dispatcher skill (echoes via cat executor, idempotent)
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS))

from migrate import PROTOCOL_HEADING  # type: ignore  # noqa: E402
from render import (  # type: ignore  # noqa: E402
    open_directions,
    CONVENTION_VERSION,
    Fragment,
    _parse_frontmatter,
    derive_identity,
    filter_fragments,
    lane_of,
    load_fragments,
    load_report,
    render_changes_summary_block,
    render_for_agent,
    view_changes_summary,
    view_doctor,
    view_effective,
    view_goals,
    view_journal,
    view_list,
)


def _make_root() -> tuple[Path, Path]:
    root = Path(tempfile.mkdtemp(prefix="sula-test-"))
    frags = root / "fragments"
    frags.mkdir()
    return root, frags


def _write(
    frags_dir: Path,
    *,
    time: str,
    slug: str,
    kind: str,
    body: str = "",
    refs: list[str] | None = None,
    tags: list[str] | None = None,
    extras: dict[str, object] | None = None,
) -> str:
    safe = time.replace(":", "-")
    fid = f"{safe}--{slug}"
    fm = ["---", f"id: {fid}", f"time: {time}", f"kind: {kind}"]
    if refs:
        fm.append(f"refs: [{', '.join(refs)}]")
    if tags:
        fm.append(f"tags: [{', '.join(tags)}]")
    if extras:
        for k, v in extras.items():
            fm.append(f"{k}: {v}")
    fm.append("---")
    (frags_dir / f"{fid}.md").write_text(
        "\n".join(fm) + "\n" + body + "\n", encoding="utf-8"
    )
    return fid


class TestFrontmatterParser(unittest.TestCase):
    def test_required_fields(self):
        text = "---\nid: a\ntime: 2026-05-23T00:00:00Z\nkind: decision\n---\nbody"
        meta, body = _parse_frontmatter(text)
        self.assertEqual(meta["id"], "a")
        self.assertEqual(meta["time"], "2026-05-23T00:00:00Z")
        self.assertEqual(meta["kind"], "decision")
        self.assertEqual(body, "body")

    def test_inline_list(self):
        text = "---\nid: x\ntime: 2026-05-23T00:00:00Z\nkind: x\nrefs: [a, b, c]\n---\n"
        meta, _ = _parse_frontmatter(text)
        self.assertEqual(meta["refs"], ["a", "b", "c"])

    def test_quoted_value(self):
        text = '---\nid: x\ntime: t\nkind: "decision"\n---\nbody'
        meta, _ = _parse_frontmatter(text)
        self.assertEqual(meta["kind"], "decision")

    def test_booleans(self):
        text = "---\nid: x\ntime: t\nkind: x\npinned: true\npassed: false\n---\nbody"
        meta, _ = _parse_frontmatter(text)
        self.assertTrue(meta["pinned"])
        self.assertFalse(meta["passed"])

    def test_no_frontmatter(self):
        meta, body = _parse_frontmatter("just text")
        self.assertEqual(meta, {})
        self.assertEqual(body, "just text")

    def test_unterminated_frontmatter(self):
        text = "---\nid: x\ntime: t\nkind: x\nno closing"
        meta, _ = _parse_frontmatter(text)
        self.assertEqual(meta, {})

    def test_empty_block_list(self):
        text = "---\nid: x\ntime: t\nkind: x\nrefs:\n  - one\n  - two\n---\nbody"
        meta, _ = _parse_frontmatter(text)
        self.assertEqual(meta["refs"], ["one", "two"])


class TestFragmentLoading(unittest.TestCase):
    def setUp(self):
        self.root, self.frags = _make_root()

    def tearDown(self):
        shutil.rmtree(self.root)

    def test_never_drops_file_without_frontmatter(self):
        (self.frags / "junk.md").write_text("just text", encoding="utf-8")
        frags, problems = load_report(self.frags)
        self.assertEqual(len(frags), 1)
        self.assertIn("no-frontmatter", {p.code for p in problems})

    def test_never_drops_file_missing_kind(self):
        (self.frags / "broken.md").write_text("---\nid: x\n---\nbody", encoding="utf-8")
        frags, problems = load_report(self.frags)
        self.assertEqual(len(frags), 1)
        self.assertEqual(frags[0].kind, "unknown")
        self.assertIn("missing-kind", {p.code for p in problems})

    def test_loads_valid(self):
        _write(self.frags, time="2026-05-23T00:00:00Z", slug="d", kind="decision")
        loaded = load_fragments(self.frags)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].kind, "decision")

    def test_orders_by_time(self):
        _write(self.frags, time="2026-05-23T02:00:00Z", slug="b", kind="fact", body="B")
        _write(self.frags, time="2026-05-23T01:00:00Z", slug="a", kind="fact", body="A")
        loaded = load_fragments(self.frags)
        self.assertEqual([f.body for f in loaded], ["A", "B"])

    def test_recursive_load(self):
        sub = self.frags / "sub"
        sub.mkdir()
        _write(sub, time="2026-05-23T00:00:00Z", slug="d", kind="decision")
        self.assertEqual(len(load_fragments(self.frags)), 1)

    def test_unreadable_file_is_reported_not_raised(self):
        path = self.frags / "2026-05-23T00-00-00Z--bad.md"
        path.write_bytes(b"\xff\xfe\x00")
        frags, problems = load_report(self.frags)
        self.assertEqual([p.code for p in problems], ["unreadable"])
        report = view_doctor(frags, problems)
        self.assertIn("unreadable", report["by_code"])
        self.assertFalse(report["ok"])


class TestViews(unittest.TestCase):
    def setUp(self):
        self.root, self.frags = _make_root()
        # one decision, one fact, one open goal, one closed intent
        _write(self.frags, time="2026-05-01T00:00:00Z", slug="d1", kind="decision", body="D1")
        _write(self.frags, time="2026-05-02T00:00:00Z", slug="f1", kind="fact", body="F1")
        _write(
            self.frags,
            time="2026-05-03T00:00:00Z",
            slug="g1",
            kind="goal",
            body="G1",
            extras={"done_when": "x", "verifier_ref": "shell:true"},
        )
        intent_id = _write(
            self.frags,
            time="2026-05-04T00:00:00Z",
            slug="i1",
            kind="intent",
            body="I1",
            extras={"done_when": "y"},
        )
        _write(
            self.frags,
            time="2026-05-05T00:00:00Z",
            slug="vf1",
            kind="verification-fact",
            body="vf",
            refs=[intent_id],
            extras={"passed": "true"},
        )

    def tearDown(self):
        shutil.rmtree(self.root)


    def test_goals_join_verification(self):
        rows = view_goals(load_fragments(self.frags))
        self.assertEqual(len(rows), 2)
        met = [r for r in rows if r["met"]]
        self.assertEqual(len(met), 1)
        self.assertIn("i1", met[0]["goal"]["id"])
        open_ids = [f.id for f in open_directions(load_fragments(self.frags))]
        self.assertEqual(len(open_ids), 1)
        self.assertIn("g1", open_ids[0])

    def test_goals_view(self):
        rows = [r for r in view_goals(load_fragments(self.frags)) if r["goal"]["kind"] == "goal"]
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["met"])

    def test_changes_summary_counts(self):
        s = view_changes_summary(load_fragments(self.frags))
        self.assertEqual(s["total"], 5)
        self.assertEqual(s["by_kind"]["decision"], 1)
        self.assertEqual(s["by_kind"]["verification-fact"], 1)
        self.assertEqual(len(s["fragments"]), 5)

    def test_changes_summary_block_silent_on_empty(self):
        self.assertEqual(render_changes_summary_block([]), "[sula] no changes")

    def test_changes_summary_block_marks_pass(self):
        block = render_changes_summary_block(load_fragments(self.frags))
        self.assertIn("[sula] +5 this turn:", block)
        self.assertIn("✓ verification-fact", block)


class TestIntentSatisfaction(unittest.TestCase):
    """A failed verification must never close the direction it refutes."""

    def setUp(self):
        self.root, self.frags = _make_root()

    def tearDown(self):
        shutil.rmtree(self.root)

    def _intent_with(self, *, passed: object | None = None):
        iid = _write(
            self.frags,
            time="2026-05-10T00:00:00Z",
            slug="direction",
            kind="intent",
            body="direction",
            extras={"done_when": "the verifier passes"},
        )
        extras: dict[str, object] = {}
        if passed is not None:
            extras["passed"] = passed
        _write(
            self.frags,
            time="2026-05-11T00:00:00Z",
            slug="result",
            kind="verification-fact",
            body="result",
            refs=[iid],
            extras=extras,
        )
        return iid

    def test_failed_verification_keeps_intent_open(self):
        iid = self._intent_with(passed="false")
        frags = load_fragments(self.frags)
        open_ids = [f.id for f in open_directions(frags)]
        self.assertIn(iid, open_ids)
        row = next(r for r in view_goals(frags) if r["goal"]["id"] == iid)
        self.assertFalse(row["met"])

    def test_passing_verification_satisfies_intent(self):
        iid = self._intent_with(passed="true")
        frags = load_fragments(self.frags)
        open_ids = [f.id for f in open_directions(frags)]
        self.assertNotIn(iid, open_ids)
        row = next(r for r in view_goals(frags) if r["goal"]["id"] == iid)
        self.assertTrue(row["met"])

    def test_plain_fact_backref_does_not_satisfy_intent(self):
        iid = _write(
            self.frags,
            time="2026-05-10T00:00:00Z",
            slug="direction",
            kind="intent",
            body="direction",
            extras={"done_when": "the verifier passes"},
        )
        _write(
            self.frags,
            time="2026-05-11T00:00:00Z",
            slug="neutral",
            kind="fact",
            body="something happened",
            refs=[iid],
        )
        frags = load_fragments(self.frags)
        open_ids = [f.id for f in open_directions(frags)]
        self.assertIn(iid, open_ids)

    def test_explicit_close_still_satisfies_intent(self):
        iid = _write(
            self.frags,
            time="2026-05-10T00:00:00Z",
            slug="direction",
            kind="intent",
            body="direction",
            extras={"done_when": "the verifier passes"},
        )
        _write(
            self.frags,
            time="2026-05-11T00:00:00Z",
            slug="closing",
            kind="fact",
            body="closed by operator",
            extras={"closes": f"[{iid}]"},
        )
        frags = load_fragments(self.frags)
        open_ids = [f.id for f in open_directions(frags)]
        self.assertNotIn(iid, open_ids)

    def test_goal_without_done_when_keeps_existing_semantics(self):
        gid = _write(
            self.frags,
            time="2026-05-10T00:00:00Z",
            slug="goal",
            kind="goal",
            body="goal",
            extras={"verifier_ref": "shell: true"},
        )
        _write(
            self.frags,
            time="2026-05-11T00:00:00Z",
            slug="pass",
            kind="verification-fact",
            body="pass",
            refs=[gid],
            extras={"passed": "true"},
        )
        frags = load_fragments(self.frags)
        open_ids = [f.id for f in open_directions(frags)]
        self.assertNotIn(gid, open_ids)




class TestMigrateIdempotence(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="sula-test-mig-"))
        # Build a synthetic legacy Sula project layout
        (self.root / "docs" / "change-records").mkdir(parents=True)
        (self.root / "docs" / "releases").mkdir(parents=True)
        sula = self.root / ".sula"
        (sula / "events").mkdir(parents=True)
        (sula / "artifacts").mkdir(parents=True)
        (self.root / "docs" / "change-records" / "2026-05-01-foo.md").write_text(
            "# Foo\n\nBody.\n", encoding="utf-8"
        )
        (self.root / "docs" / "releases" / "2026-05-02-release-x.md").write_text(
            "# Release X\n", encoding="utf-8"
        )
        (self.root / "STATUS.md").write_text("# STATUS\nbody\n", encoding="utf-8")
        (sula / "project.toml").write_text("[project]\nname = 'test'\n", encoding="utf-8")
        (sula / "events" / "log.jsonl").write_text(
            '{"timestamp":"2026-05-01T00:00:00Z","event_type":"record.change","summary":"X"}\n'
            '{"timestamp":"2026-05-01T00:00:00Z","event_type":"record.change","summary":"X"}\n'  # dup
            '{"timestamp":"2026-05-01T00:00:01Z","event_type":"sync.applied","summary":"noise"}\n',
            encoding="utf-8",
        )
        (sula / "artifacts" / "catalog.json").write_text(
            json.dumps({"artifacts": [{"id": "a1", "title": "A1", "kind": "report"}]}),
            encoding="utf-8",
        )

    def tearDown(self):
        shutil.rmtree(self.root)

    def _run_migrate(self):
        result = subprocess.run(
            [
                "python3",
                str(TOOLS / "migrate.py"),
                "--project-root",
                str(self.root),
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def test_first_run_produces_expected_kinds(self):
        self._run_migrate()
        frags = load_fragments(self.root / "fragments")
        kinds = {f.kind for f in frags}
        self.assertIn("decision", kinds)  # change-record + manifest + migration-decision
        self.assertIn("release", kinds)
        self.assertIn("snapshot", kinds)  # STATUS.md
        self.assertIn("artifact", kinds)
        self.assertIn("event", kinds)

    def test_second_run_is_noop(self):
        self._run_migrate()
        before = sorted(p.name for p in (self.root / "fragments").glob("*.md"))
        self._run_migrate()
        after = sorted(p.name for p in (self.root / "fragments").glob("*.md"))
        self.assertEqual(before, after)

    def test_event_dedup(self):
        self._run_migrate()
        events = [
            f
            for f in load_fragments(self.root / "fragments")
            if f.kind == "event"
        ]
        # Two duplicate record.change events in source must collapse to one
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].get("event_type"), "record.change")

    def test_legacy_dirs_untouched(self):
        self._run_migrate()
        self.assertTrue((self.root / ".sula").is_dir())
        self.assertTrue((self.root / "STATUS.md").exists())
        self.assertTrue(
            (self.root / "docs" / "change-records" / "2026-05-01-foo.md").exists()
        )


class TestFleetUpdate(unittest.TestCase):
    """migrate.py is the update path, so a fleet rollout is only as good as it.

    An already-adopted project must come out of an update with the protocol its
    tools actually implement, and with a usable done-gate.
    """

    SENTINEL = "<!-- sula-vector -->"

    def setUp(self):
        self.root, self.frags = _make_root()
        sys.path.insert(0, str(TOOLS))

    def tearDown(self):
        shutil.rmtree(self.root)

    def _migrate(self, *args: str) -> subprocess.CompletedProcess:
        result = subprocess.run(
            [
                sys.executable,
                str(TOOLS / "migrate.py"),
                "--project-root",
                str(self.root),
                *args,
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def _stale_agents(self) -> None:
        (self.root / "AGENTS.md").write_text(
            "# Project's own notes\n\nKeep this line.\n\n---\n\n"
            f"{self.SENTINEL}\n# AGENTS.md — Sula Vector\n\n"
            "Stale protocol: the omission is inherited, not forgotten.\n",
            encoding="utf-8",
        )

    def _unclaimed_capture(self, time: str, slug: str, body: str) -> str:
        return _write(
            self.frags,
            time=time,
            slug=slug,
            kind="witness",
            body=body,
            extras={"files_changed": 1},
        )

    def test_stale_protocol_is_refreshed(self):
        """Stale protocol is worse than none: the agent boots on a moved contract."""
        self._stale_agents()
        self._migrate()
        text = (self.root / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("Keep this line.", text)
        self.assertNotIn("inherited, not forgotten", text)
        self.assertIn("rules.py", text)

    def test_protocol_refresh_is_idempotent(self):
        self._stale_agents()
        self._migrate()
        first = (self.root / "AGENTS.md").read_text(encoding="utf-8")
        result = self._migrate()
        self.assertEqual((self.root / "AGENTS.md").read_text(encoding="utf-8"), first)
        self.assertIn("unchanged", result.stdout)

    def test_foreign_text_after_sentinel_is_left_alone(self):
        """Deleting a project's own text is the worse failure of the two."""
        own = f"# Notes\n\n{self.SENTINEL}\n\nSomething this project wrote itself.\n"
        (self.root / "AGENTS.md").write_text(own, encoding="utf-8")
        result = self._migrate()
        text = (self.root / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("Something this project wrote itself.", text)
        self.assertNotIn(PROTOCOL_HEADING, text)
        self.assertIn("protocol-foreign-left-alone", result.stdout)


    def test_installed_tooling_matches_the_updater_hash_list(self):
        """Two lists of tooling files drift; the updater then reports up to date."""
        sys.path.insert(0, str(TOOLS))
        from migrate import TOOLING_FILES  # type: ignore

        from migrate import RETIRED_FILES  # type: ignore

        for rel in TOOLING_FILES:
            self.assertTrue((TOOLS / rel).is_file(), rel)
        for rel in RETIRED_FILES:
            self.assertFalse((TOOLS / rel).exists(), rel)
        self.assertIn("rules.py", TOOLING_FILES)


class TestVerifierShellSkill(unittest.TestCase):
    def setUp(self):
        self.root, self.frags = _make_root()

    def tearDown(self):
        shutil.rmtree(self.root)

    def _run(self):
        result = subprocess.run(
            [
                "python3",
                str(TOOLS / "skills" / "verifier-shell.py"),
                "--project-root",
                str(self.root),
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def test_closes_goal_with_passing_command(self):
        gid = _write(
            self.frags,
            time="2026-05-23T00:00:00Z",
            slug="goal-true",
            kind="goal",
            body="must run true",
            extras={"done_when": "true exits 0", "verifier_ref": "shell:true"},
        )
        self._run()
        verified = [
            f
            for f in load_fragments(self.frags)
            if f.kind == "verification-fact" and gid in f.refs
        ]
        self.assertEqual(len(verified), 1)
        self.assertIn(verified[0].get("passed"), {True, "true"})

    def test_idempotent_on_satisfied_goal(self):
        _write(
            self.frags,
            time="2026-05-23T00:00:00Z",
            slug="goal-true2",
            kind="goal",
            extras={"done_when": "true", "verifier_ref": "shell:true"},
        )
        self._run()
        before = len(list(self.frags.glob("*.md")))
        self._run()
        after = len(list(self.frags.glob("*.md")))
        self.assertEqual(before, after)




class TestConventionVersion(unittest.TestCase):
    def test_version_is_one_three(self):
        self.assertEqual(CONVENTION_VERSION, "1.3")


class TestDerivedIdentity(unittest.TestCase):
    def setUp(self):
        self.root, self.frags = _make_root()

    def tearDown(self):
        shutil.rmtree(self.root)

    def test_identity_comes_from_filename(self):
        stem = "2026-07-01T09-08-07Z--decision-x"
        (self.frags / f"{stem}.md").write_text(
            "---\nkind: decision\n---\nonly kind was authored\n", encoding="utf-8"
        )
        frags, problems = load_report(self.frags)
        self.assertEqual(problems, [])
        self.assertEqual(frags[0].id, stem)
        self.assertEqual(frags[0].time, "2026-07-01T09:08:07Z")

    def test_derive_identity_helper(self):
        fid, time = derive_identity(Path("2026-07-01T09-08-07Z--goal-y.md"))
        self.assertEqual(fid, "2026-07-01T09-08-07Z--goal-y")
        self.assertEqual(time, "2026-07-01T09:08:07Z")

    def test_frontmatter_disagreement_is_reported_filename_wins(self):
        stem = "2026-07-01T09-08-07Z--decision-x"
        (self.frags / f"{stem}.md").write_text(
            "---\nid: wrong-id\ntime: 2020-01-01T00:00:00Z\nkind: decision\n---\nb\n",
            encoding="utf-8",
        )
        frags, problems = load_report(self.frags)
        codes = [p.code for p in problems]
        self.assertEqual(codes.count("header-disagreement"), 2)
        self.assertEqual(frags[0].id, stem)
        self.assertEqual(frags[0].time, "2026-07-01T09:08:07Z")


class TestDoctor(unittest.TestCase):
    def setUp(self):
        self.root, self.frags = _make_root()

    def tearDown(self):
        shutil.rmtree(self.root)

    def _doctor(self):
        frags, problems = load_report(self.frags)
        return view_doctor(frags, problems)

    def test_clean_vector_is_ok(self):
        _write(self.frags, time="2026-05-23T00:00:00Z", slug="d", kind="decision", body="x")
        report = self._doctor()
        self.assertTrue(report["ok"])
        self.assertEqual(report["problems"], [])

    def test_dangling_ref_detected(self):
        _write(
            self.frags,
            time="2026-05-23T00:00:00Z",
            slug="d",
            kind="decision",
            body="x",
            refs=["2026-01-01T00-00-00Z--does-not-exist"],
        )
        self.assertIn("dangling-ref", self._doctor()["by_code"])

    def test_dangling_ref_acknowledged_by_correction(self):
        missing = "2026-01-01T00-00-00Z--does-not-exist"
        _write(
            self.frags,
            time="2026-05-23T00:00:00Z",
            slug="d",
            kind="decision",
            body="x",
            refs=[missing],
        )
        _write(
            self.frags,
            time="2026-05-24T00:00:00Z",
            slug="correction-ack",
            kind="correction",
            body="that id never existed",
            extras={"broken_ref": missing},
        )
        self.assertTrue(self._doctor()["ok"])

    def test_goal_without_verifier_detected(self):
        _write(self.frags, time="2026-05-23T00:00:00Z", slug="g", kind="goal", body="x")
        self.assertIn("goal-without-verifier", self._doctor()["by_code"])

    def test_symbolic_refs_are_not_dangling(self):
        _write(
            self.frags,
            time="2026-05-23T00:00:00Z",
            slug="d",
            kind="decision",
            body="x",
            refs=["family:acme-intake"],
        )
        self.assertTrue(self._doctor()["ok"])

    def test_cli_exit_code(self):
        _write(
            self.frags,
            time="2026-05-23T00:00:00Z",
            slug="d",
            kind="decision",
            body="x",
            refs=["nope"],
        )
        result = subprocess.run(
            [sys.executable, str(TOOLS / "render.py"), str(self.root), "--view", "doctor"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("dangling-ref", result.stdout)


class TestSupersessionAndClosure(unittest.TestCase):
    def setUp(self):
        self.root, self.frags = _make_root()
        self.old = _write(
            self.frags, time="2026-05-01T00:00:00Z", slug="d-old", kind="decision", body="old way"
        )
        self.new = _write(
            self.frags,
            time="2026-05-02T00:00:00Z",
            slug="d-new",
            kind="decision",
            body="new way",
            extras={"supersedes": f"[{self.old}]"},
        )

    def tearDown(self):
        shutil.rmtree(self.root)

    def test_effective_splits_in_force_and_retired(self):
        result = view_effective(load_fragments(self.frags))
        self.assertEqual([f["id"] for f in result["in_force"]], [self.new])
        self.assertEqual([f["id"] for f in result["retired"]], [self.old])
        self.assertEqual(result["retired"][0]["superseded_by"][0]["id"], self.new)

    def test_superseded_judgment_hidden_from_boot(self):
        out = render_for_agent(load_fragments(self.frags))
        self.assertIn(self.new, out)
        self.assertNotIn(self.old, out)

    def test_closes_removes_open_direction(self):
        intent = _write(
            self.frags, time="2026-05-03T00:00:00Z", slug="i", kind="intent", body="do a thing"
        )
        self.assertIn(intent, [f.id for f in open_directions(load_fragments(self.frags))])
        _write(
            self.frags,
            time="2026-05-04T00:00:00Z",
            slug="f",
            kind="fact",
            body="thing done",
            extras={"closes": f"[{intent}]"},
        )
        self.assertEqual(open_directions(load_fragments(self.frags)), [])

    def test_superseded_principle_leaves_force(self):
        p_old = _write(
            self.frags,
            time="2026-05-05T00:00:00Z",
            slug="principle-old",
            kind="principle",
            body="old principle",
            extras={"tier": "aesthetic"},
        )
        _write(
            self.frags,
            time="2026-05-06T00:00:00Z",
            slug="principle-new",
            kind="principle",
            body="new principle",
            extras={"tier": "aesthetic", "supersedes": f"[{p_old}]"},
        )
        out = render_for_agent(load_fragments(self.frags))
        self.assertIn("new principle", out)
        self.assertNotIn("old principle", out)


class TestLanesAndJournal(unittest.TestCase):
    def setUp(self):
        self.root, self.frags = _make_root()

    def tearDown(self):
        shutil.rmtree(self.root)

    def test_lane_defaults(self):
        cases = {
            "decision": "judgment",
            "correction": "judgment",
            "goal": "direction",
            "intent": "direction",
            "witness": "evidence",
            "artifact": "evidence",
            "some-new-kind": "evidence",
        }
        for kind, lane in cases.items():
            self.assertEqual(lane_of(Fragment(id="x", time="t", kind=kind)), lane)

    def test_explicit_lane_overrides(self):
        f = Fragment(id="x", time="t", kind="artifact", extra={"lane": "judgment"})
        self.assertEqual(lane_of(f), "judgment")

    def test_lane_filter(self):
        _write(self.frags, time="2026-05-01T00:00:00Z", slug="d", kind="decision", body="d")
        _write(self.frags, time="2026-05-02T00:00:00Z", slug="w", kind="witness", body="w")
        frags = load_fragments(self.frags)
        self.assertEqual(len(filter_fragments(frags, lane="judgment")), 1)
        self.assertEqual(len(filter_fragments(frags, lane="evidence")), 1)

    def test_journal_groups_by_day(self):
        _write(self.frags, time="2026-05-01T09:00:00Z", slug="d", kind="decision", body="chose X")
        _write(
            self.frags,
            time="2026-05-01T10:00:00Z",
            slug="a",
            kind="artifact",
            body="proposal",
            extras={"pointer": "docs/p.pdf"},
        )
        _write(self.frags, time="2026-05-02T09:00:00Z", slug="w", kind="witness", body="+1 file")
        journal = view_journal(load_fragments(self.frags))
        self.assertEqual([d["day"] for d in journal], ["2026-05-01", "2026-05-02"])
        self.assertEqual(len(journal[0]["judgment"]), 1)
        self.assertEqual(journal[0]["evidence"][0]["pointer"], "docs/p.pdf")


class TestNoteCli(unittest.TestCase):
    def setUp(self):
        self.root, self.frags = _make_root()

    def tearDown(self):
        shutil.rmtree(self.root)

    def _note(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(TOOLS / "note.py"), str(self.root), *args],
            capture_output=True,
            text=True,
        )

    def test_appends_clean_fragment(self):
        result = self._note("--kind", "decision", "--title", "pick A", "because faster")
        self.assertEqual(result.returncode, 0, result.stderr)
        frags, problems = load_report(self.frags)
        self.assertEqual(problems, [])
        self.assertEqual(len(frags), 1)
        self.assertEqual(frags[0].kind, "decision")
        self.assertEqual(frags[0].get("summary"), "pick A")
        self.assertEqual(frags[0].id, Path(frags[0].path).stem)

    def test_echoes_derived_lane(self):
        result = self._note("--kind", "decision", "--title", "pick A", "why")
        self.assertIn("→ judgment", result.stdout)
        result = self._note("--kind", "event", "--title", "a thing happened", "what")
        self.assertIn("→ evidence", result.stdout)

    def test_rejects_unknown_ref(self):
        result = self._note("--kind", "decision", "--refs", "nope", "body")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(list(self.frags.glob("*.md")), [])

    def test_rejects_goal_without_verifier(self):
        result = self._note("--kind", "goal", "--title", "ship it", "body")
        self.assertEqual(result.returncode, 2)

    def test_non_ascii_body_yields_safe_filename(self):
        result = self._note("--kind", "decision", "对 Acme 采用月度交付节奏")
        self.assertEqual(result.returncode, 0, result.stderr)
        name = next(self.frags.glob("*.md")).name
        self.assertTrue(name.isascii(), name)

    def test_same_second_appends_do_not_collide(self):
        for _ in range(3):
            self.assertEqual(self._note("--kind", "fact", "--title", "same", "x").returncode, 0)
        frags, problems = load_report(self.frags)
        self.assertEqual(len(frags), 3)
        self.assertNotIn("duplicate-id", view_doctor(frags, problems)["by_code"])

    def test_rejects_unknown_explains_target(self):
        result = self._note("--kind", "decision", "--explains", "nope", "body")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(list(self.frags.glob("*.md")), [])

    def test_rejects_reserved_field_override(self):
        for key in ("kind", "id", "time", "refs"):
            result = self._note(
                "--kind", "decision", "--title", "x", "--field", f"{key}=nope", "body"
            )
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn(f"reserved key: {key}", result.stderr)
        self.assertEqual(list(self.frags.glob("*.md")), [])

    def test_accepts_symbolic_refs_doctor_ignores(self):
        result = self._note(
            "--kind", "decision", "--refs", "family:demo", "--title", "x", "body"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        frags, problems = load_report(self.frags)
        self.assertEqual(frags[0].refs, ["family:demo"])
        self.assertNotIn("dangling-ref", view_doctor(frags, problems)["by_code"])


class TestWitnessSkill(unittest.TestCase):
    def setUp(self):
        self.root, self.frags = _make_root()

    def tearDown(self):
        shutil.rmtree(self.root)

    def _witness(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [
                sys.executable,
                str(TOOLS / "skills" / "witness.py"),
                "--project-root",
                str(self.root),
                *args,
            ],
            capture_output=True,
            text=True,
        )

    def test_newline_in_filename_does_not_churn(self):
        """A newline in a filename must not break the delta round-trip.

        Found on an iCloud folder of documents synced from another tool: the
        path split the delta line, folded back truncated, and the file was
        reported added and removed on every run forever.
        """
        (self.root / "note\nwith newline.md").write_text("x", encoding="utf-8")
        self.assertEqual(self._witness().returncode, 0)
        second = self._witness()
        self.assertIn("no change", second.stdout)

    def test_captures_added_changed_removed(self):
        (self.root / "notes.md").write_text("one", encoding="utf-8")
        self.assertEqual(self._witness().returncode, 0)
        witnesses = [f for f in load_fragments(self.frags) if f.kind == "witness"]
        self.assertEqual(len(witnesses), 1)
        self.assertEqual(witnesses[0].get("files_added"), "1")

        (self.root / "notes.md").write_text("two", encoding="utf-8")
        self._witness()
        (self.root / "notes.md").unlink()
        self._witness()
        witnesses = [f for f in load_fragments(self.frags) if f.kind == "witness"]
        self.assertEqual(len(witnesses), 3)
        self.assertEqual(witnesses[1].get("files_changed"), "1")
        self.assertEqual(witnesses[2].get("files_removed"), "1")

    def _note(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(TOOLS / "note.py"), str(self.root), *args],
            capture_output=True,
            text=True,
        )



    def test_idempotent_when_nothing_changed(self):
        (self.root / "notes.md").write_text("one", encoding="utf-8")
        self._witness()
        before = len(list(self.frags.glob("*.md")))
        result = self._witness()
        self.assertIn("no change", result.stdout)
        self.assertEqual(len(list(self.frags.glob("*.md"))), before)

    def test_documents_become_artifact_fragments(self):
        (self.root / "proposal.pdf").write_text("pdf", encoding="utf-8")
        (self.root / "script.py").write_text("code", encoding="utf-8")
        self._witness()
        frags = load_fragments(self.frags)
        artifacts = [f for f in frags if f.kind == "artifact"]
        self.assertEqual([f.get("pointer") for f in artifacts], ["proposal.pdf"])

    def test_state_is_folded_not_stored(self):
        (self.root / "a.md").write_text("a", encoding="utf-8")
        self._witness()
        self.assertFalse((self.root / ".sula").exists())
        self.assertEqual(
            sorted(p.name for p in self.root.iterdir()), ["a.md", "fragments"]
        )

    def test_output_is_clean_for_doctor(self):
        (self.root / "proposal.pdf").write_text("pdf", encoding="utf-8")
        self._witness("--label", "定稿")
        frags, problems = load_report(self.frags)
        self.assertTrue(view_doctor(frags, problems)["ok"])

    def test_rejects_unknown_refs(self):
        (self.root / "a.md").write_text("a", encoding="utf-8")
        result = self._witness("--refs", "nope")
        self.assertEqual(result.returncode, 2)

    def test_fragment_only_commits_do_not_loop(self):
        def git(*cmd):
            subprocess.run(["git", *cmd], cwd=str(self.root), check=True,
                           capture_output=True, text=True)
        git("init", "-q")
        git("config", "user.email", "t@example.com")
        git("config", "user.name", "t")
        (self.root / "report.md").write_text("v1", encoding="utf-8")
        git("add", "-A")
        git("commit", "-qm", "add report")
        self.assertEqual(self._witness().returncode, 0)
        # commit the witness fragment itself, then witness again: no churn
        git("add", "-A")
        git("commit", "-qm", "capture")
        before = len(list(self.frags.glob("*.md")))
        result = self._witness()
        self.assertIn("no change", result.stdout)
        self.assertEqual(len(list(self.frags.glob("*.md"))), before)



class TestBrokenRefRepair(unittest.TestCase):
    """The repair path for a dangling ref has to scale, or the gate never reopens.

    A fragment holding a bad ref can never be edited (B1), so acknowledgement is
    the only route. One project carries 483 of them from hand-written v1.0-era
    fragments; one fragment per ref is a path nobody walks.
    """

    def setUp(self):
        self.root, self.frags = _make_root()

    def tearDown(self):
        shutil.rmtree(self.root)

    def _doctor(self):
        frags, problems = load_report(self.frags)
        return view_doctor(frags, problems)

    def _dangling(self, slug: str, target: str) -> None:
        _write(
            self.frags,
            time=f"2026-05-01T00:00:0{slug[-1]}Z",
            slug=slug,
            kind="decision",
            body="points at something that never existed",
            refs=[target],
        )

    def test_one_fragment_acknowledges_many(self):
        missing = [f"2026-01-01T00-00-0{i}Z--gone" for i in range(3)]
        for i, target in enumerate(missing):
            self._dangling(f"d{i}", target)
        self.assertEqual(self._doctor()["by_code"]["dangling-ref"], 3)
        _write(
            self.frags,
            time="2026-06-01T00:00:00Z",
            slug="correction-bulk",
            kind="correction",
            body="none of these ids were ever written",
            extras={"broken_ref": f"[{', '.join(missing)}]"},
        )
        self.assertTrue(self._doctor()["ok"])

    def test_scalar_form_still_acknowledges(self):
        """v1.0-era fragments wrote a single id; they must keep working."""
        missing = "2026-01-01T00-00-00Z--gone"
        self._dangling("d0", missing)
        _write(
            self.frags,
            time="2026-06-01T00:00:00Z",
            slug="correction-scalar",
            kind="correction",
            body="that id never existed",
            extras={"broken_ref": missing},
        )
        self.assertTrue(self._doctor()["ok"])

    def test_partial_acknowledgement_leaves_the_rest(self):
        self._dangling("d0", "2026-01-01T00-00-00Z--gone")
        self._dangling("d1", "2026-01-01T00-00-01Z--also-gone")
        _write(
            self.frags,
            time="2026-06-01T00:00:00Z",
            slug="correction-partial",
            kind="correction",
            body="only the first is accounted for",
            extras={"broken_ref": "[2026-01-01T00-00-00Z--gone]"},
        )
        self.assertEqual(self._doctor()["by_code"]["dangling-ref"], 1)

    def test_note_does_not_validate_broken_refs(self):
        """They are broken because nothing carries them; validating is impossible."""
        result = subprocess.run(
            [
                sys.executable,
                str(TOOLS / "note.py"),
                str(self.root),
                "--kind",
                "correction",
                "--broken-ref",
                "2026-01-01T00-00-00Z--gone,2026-01-01T00-00-01Z--also-gone",
                "neither id was ever written",
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        written = next(f for f in load_fragments(self.frags) if f.kind == "correction")
        self.assertEqual(
            written.id_list("broken_ref"),
            ["2026-01-01T00-00-00Z--gone", "2026-01-01T00-00-01Z--also-gone"],
        )




class TestHostPointers(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="sula-test-host-"))

    def tearDown(self):
        shutil.rmtree(self.root)

    def test_projects_all_hosts_and_is_idempotent(self):
        sys.path.insert(0, str(TOOLS))
        from migrate import HOST_POINTER_TARGETS, install_host_pointers  # type: ignore

        written, skipped = install_host_pointers(self.root)
        self.assertEqual(written, len(HOST_POINTER_TARGETS))
        self.assertEqual(skipped, 0)
        for rel in HOST_POINTER_TARGETS:
            text = (self.root / rel).read_text(encoding="utf-8")
            self.assertIn("AGENTS.md", text)
            self.assertIn("--for-agent", text)
        self.assertEqual(install_host_pointers(self.root), (0, 0))

    def test_custom_host_pointer_is_preserved_not_overwritten(self):
        sys.path.insert(0, str(TOOLS))
        from migrate import HOST_POINTER_TARGETS, install_host_pointers  # type: ignore

        (self.root / "CLAUDE.md").write_text("# my custom rules\n", encoding="utf-8")
        written, skipped = install_host_pointers(self.root)
        self.assertEqual(written, len(HOST_POINTER_TARGETS) - 1)
        self.assertEqual(skipped, 1)
        text = (self.root / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertIn("my custom rules", text)
        self.assertNotIn("Sula Vector convention", text)

    def test_empty_host_pointer_is_filled(self):
        sys.path.insert(0, str(TOOLS))
        from migrate import install_host_pointers  # type: ignore

        (self.root / "CLAUDE.md").write_text("", encoding="utf-8")
        written, skipped = install_host_pointers(self.root)
        self.assertEqual(skipped, 0)
        self.assertIn(
            "Sula Vector convention",
            (self.root / "CLAUDE.md").read_text(encoding="utf-8"),
        )

    def test_agents_protocol_is_projected_from_template(self):
        sys.path.insert(0, str(TOOLS))
        from migrate import install_agents_template  # type: ignore

        (self.root / "AGENTS.md").write_text("# legacy rules\n", encoding="utf-8")
        install_agents_template(self.root, TOOLS / "AGENTS.md")
        text = (self.root / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("<!-- sula-vector -->", text)
        self.assertIn("rule sheet", text)
        self.assertNotIn("path/to/", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
