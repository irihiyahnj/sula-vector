"""Behavioral invariants for immutable writing, evidence and project handoffs."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS))
from append import append_fragment, publish
from capture import CaptureError, capture_graph, fold_witnessed, hash_file, scan_tree, tree_digest
from render import Fragment, load_fragments, load_report, render_for_agent, view_doctor, view_goals


def skill(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), TOOLS / "skills" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ProjectCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="sula-reliability-")).resolve()
        self.frags = self.root / "fragments"
        self.frags.mkdir()

    def tearDown(self):
        shutil.rmtree(self.root)

    def add(self, kind, body="context", **fields):
        return append_fragment(self.frags, kind, {"kind": kind, **fields}, body).stem

    def run_tool(self, name, *args):
        return subprocess.run([sys.executable, str(TOOLS / name), *args], capture_output=True, text=True)

    def capture(self):
        result = self.run_tool("skills/witness.py", "--project-root", str(self.root))
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def render(self, *args):
        result = self.run_tool("render.py", str(self.root), *args, "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)


class TestImmutablePublication(ProjectCase):
    def test_concurrent_appends_preserve_every_body_and_old_bytes(self):
        original = append_fragment(self.frags, "same", {"kind": "fact"}, "original")
        old = original.read_bytes()
        def write(n):
            return append_fragment(self.frags, "same", {"kind": "fact"}, f"body-{n}", stamp="2026-09-05T00:00:00Z")
        with ThreadPoolExecutor(max_workers=8) as pool:
            paths = list(pool.map(write, range(40)))
        self.assertEqual(len(set(paths)), 40)
        self.assertEqual({f.body for f in load_fragments(self.frags)}, {"original", *(f"body-{n}" for n in range(40))})
        self.assertEqual(original.read_bytes(), old)
        self.assertTrue(view_doctor(*load_report(self.frags))["ok"])

    def test_publish_collision_never_replaces_content(self):
        target = self.frags / "reserved.md"
        first = "---\nkind: fact\n---\nfirst\n"
        self.assertTrue(publish(target, first))
        self.assertFalse(publish(target, "---\nkind: fact\n---\nsecond\n"))
        self.assertIn("first", target.read_text())
        self.assertNotIn("second", target.read_text())

    def test_publish_does_not_need_hard_links(self):
        with patch("os.link", side_effect=OSError("unsupported")):
            path = append_fragment(self.frags, "x", {"kind": "fact"}, "body")
        self.assertEqual([f.body for f in load_fragments(self.frags)], ["body"])
        self.assertEqual(list(self.frags.iterdir()), [path])

    def test_failed_write_leaves_no_file(self):
        with patch("append.os.fsync", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                append_fragment(self.frags, "x", {"kind": "fact"}, "body")
        self.assertEqual(list(self.frags.iterdir()), [])

    def test_torn_files_are_reported_and_never_rendered(self):
        good = append_fragment(self.frags, "ok", {"kind": "fact"}, "complete body")
        text = good.read_text()
        torn = {
            "empty": "",
            "unclosed-header": text[: text.index("kind:") + 4],
            "short-body": text[:-6] + "\n",
        }
        for name, content in torn.items():
            (self.frags / f"2026-09-06T00-00-00Z--torn-{name}.md").write_text(content)
        frags, problems = load_report(self.frags)
        self.assertEqual([f.body for f in frags], ["complete body"])
        self.assertEqual(sorted(p.code for p in problems), ["incomplete-fragment"] * 3)
        self.assertFalse(view_doctor(frags, problems)["ok"])

    def test_dot_files_are_not_fragments(self):
        append_fragment(self.frags, "ok", {"kind": "fact"}, "body")
        (self.frags / "._companion.md").write_bytes(b"\x00\x05\x16\x07\xb0")
        frags, problems = load_report(self.frags)
        self.assertEqual(len(frags), 1)
        self.assertEqual(problems, [])

    def test_legacy_fragment_without_sha256_still_loads(self):
        (self.frags / "2026-05-01T00-00-00Z--old.md").write_text("---\nkind: fact\n---\nold body\n")
        frags, problems = load_report(self.frags)
        self.assertEqual([f.body for f in frags], ["old body"])
        self.assertEqual(problems, [])

    def test_same_second_verification_results_both_survive(self):
        gid = self.add("goal", verifier_ref="shell: true")
        fields = {"kind": "verification-fact", "refs": [gid]}
        one = append_fragment(self.frags, "verification-fact", {**fields, "passed": False}, "first", stamp="2026-09-05T00:00:00Z")
        two = append_fragment(self.frags, "verification-fact", {**fields, "passed": True}, "second", stamp="2026-09-05T00:00:00Z")
        self.assertNotEqual(one, two)
        self.assertIn("first", one.read_text())
        self.assertIn("second", two.read_text())

    def test_structured_values_round_trip_without_header_injection(self):
        text = 'A\nkind: goal\nsummary: "overwritten"'
        self.add("decision", summary=text, governs=['path,with comma', 'path\nwith newline'])
        f = load_fragments(self.frags)[0]
        self.assertEqual(f.kind, "decision")
        self.assertEqual(f.get("summary"), text)
        self.assertEqual(f.id_list("governs"), ['path,with comma', 'path\nwith newline'])

    def test_fractional_time_sorts_after_whole_second(self):
        append_fragment(self.frags, "a", {"kind": "fact"}, "later", stamp="2026-09-05T00:00:00.000001Z")
        append_fragment(self.frags, "z", {"kind": "fact"}, "earlier", stamp="2026-09-05T00:00:00Z")
        self.assertEqual([f.body for f in load_fragments(self.frags)], ["earlier", "later"])



class TestProjectionConsistency(ProjectCase):
    def test_display_filters_preserve_goal_status(self):
        gid = self.add("goal", verifier_ref="shell:true", tags=["delivery"], done_when="exit zero")
        self.add("verification-fact", refs=[gid], passed=True)
        for selectors in [(), ("--kind", "goal"), ("--lane", "direction"), ("--tag", "delivery")]:
            rows = self.render("--view", "goals", *selectors)
            self.assertEqual([(r["goal"]["id"], r["met"]) for r in rows], [(gid, True)])

    def test_filtered_judgment_does_not_resurrect_superseded_rule(self):
        old = self.add("decision", "old", tags=["old"])
        self.add("correction", "new", supersedes=[old])
        rows = self.render("--view", "effective", "--kind", "decision")
        self.assertEqual(rows["in_force"], [])
        self.assertEqual(rows["retired"][0]["id"], old)


    def test_until_is_historical_while_since_is_display_only(self):
        goal = append_fragment(self.frags, "goal", {"kind": "goal", "verifier_ref": "shell:true"}, "goal", stamp="2026-01-01T00:00:00Z")
        append_fragment(self.frags, "verification", {"kind": "verification-fact", "refs": [goal.stem], "passed": True}, "pass", stamp="2026-02-01T00:00:00Z")
        self.assertFalse(self.render("--view", "goals", "--until", "2026-01-02T00:00:00Z")[0]["met"])
        self.assertTrue(self.render("--view", "goals", "--since", "2026-01-01T00:00:00Z")[0]["met"])


class TestContentCapture(ProjectCase):
    def test_whitespace_paths_round_trip(self):
        path = self.root / ' \tquoted" name.txt'
        path.write_text("one")
        self.capture()
        self.assertIn(path.name, fold_witnessed(load_fragments(self.frags))[0])
        self.assertIn("no change", self.capture().stdout)
        path.unlink()
        self.capture()
        self.assertNotIn(path.name, fold_witnessed(load_fragments(self.frags))[0])

    def test_large_same_size_edit_is_observed(self):
        path = self.root / "master.mp4"
        with path.open("wb") as handle:
            handle.truncate(50 * 1024 * 1024 + 1)
        self.capture()
        with path.open("r+b") as handle:
            handle.seek(25 * 1024 * 1024)
            handle.write(b"new")
        self.add("decision", "replace master")
        self.capture()
        frags = load_fragments(self.frags)
        witnesses = [f for f in frags if f.kind == "witness"]
        self.assertEqual(witnesses[-1].get("files_changed"), "1")
        self.assertEqual(witnesses[-1].get("hash_method"), "sha256")
        self.assertTrue(view_doctor(frags, [])["ok"])
        self.assertIn("no change", self.capture().stdout)

    def test_unreadable_file_cannot_be_reported_unchanged(self):
        path = self.root / "asset"
        path.write_bytes(b"a")
        with patch.object(Path, "open", side_effect=PermissionError("denied")):
            with self.assertRaises(CaptureError):
                hash_file(path)

    def test_empty_project_still_has_a_capture_boundary(self):
        self.capture()
        self.assertEqual(len([f for f in load_fragments(self.frags) if f.kind == "witness"]), 1)

    def test_concurrent_capture_branches_block_until_reconciled(self):
        base = self.add("witness", baseline=True, capture_format="2")
        self.add("witness", capture_format="2", capture_parents=[base], baseline=True)
        self.add("witness", capture_format="2", capture_parents=[base], baseline=True)
        blocked = self.run_tool("skills/witness.py", "--project-root", str(self.root))
        self.assertEqual(blocked.returncode, 2)
        reconciled = self.run_tool("skills/witness.py", "--project-root", str(self.root), "--reconcile")
        self.assertEqual(reconciled.returncode, 0, reconciled.stderr)
        self.assertTrue(view_doctor(*load_report(self.frags))["ok"])

    def test_missing_capture_ancestor_blocks(self):
        self.add("witness", capture_format="2", capture_parents=["missing"], baseline=True)
        blocked = self.run_tool("skills/witness.py", "--project-root", str(self.root))
        self.assertEqual(blocked.returncode, 2)

    def test_capture_ancestry_outvotes_clock_skew(self):
        base = append_fragment(self.frags, "witness", {"kind": "witness", "capture_format": "2"}, "+ a 1 " + json.dumps("x"), stamp="2026-09-05T01:00:00Z")
        append_fragment(self.frags, "witness", {"kind": "witness", "capture_format": "2", "capture_parents": [base.stem]}, "~ b 1 " + json.dumps("x"), stamp="2026-09-05T00:00:00Z")
        tree, count = fold_witnessed(load_fragments(self.frags))
        self.assertEqual(tree["x"], ("b", 1))
        self.assertEqual(count, 2)

    def test_explicit_parent_wins_over_legacy_clock_order(self):
        base = append_fragment(self.frags, "witness", {"kind": "witness"}, "+ a 1 x", stamp="2026-09-05T10:00:00Z")
        child = append_fragment(self.frags, "witness", {"kind": "witness", "capture_format": "2", "capture_parents": [base.stem]}, "~ b 1 " + json.dumps("x"), stamp="2026-09-05T09:59:00Z")
        ordered, heads, errors = capture_graph(load_fragments(self.frags))
        self.assertEqual([f.id for f in ordered], [base.stem, child.stem])
        self.assertEqual(errors, [])
        self.assertEqual(len(heads), 1)
        tree, count = fold_witnessed(load_fragments(self.frags))
        self.assertEqual(tree["x"], ("b", 1))
        self.assertEqual(count, 2)

    def test_legacy_quote_filename_survives_new_reader(self):
        base = append_fragment(self.frags, "witness", {"kind": "witness"}, '~ a 1 "file.txt"', stamp="2026-09-05T10:00:00Z")
        append_fragment(self.frags, "witness", {"kind": "witness", "capture_format": "2", "capture_parents": [base.stem]}, "+ b 1 " + json.dumps("x"), stamp="2026-09-05T10:01:00Z")
        tree, count = fold_witnessed(load_fragments(self.frags))
        self.assertIn('"file.txt"', tree)
        self.assertEqual(count, 2)

    def test_json_quoted_filename_decodes_in_new_records(self):
        quoted = json.dumps('say "hi".txt', ensure_ascii=False)
        append_fragment(self.frags, "witness", {"kind": "witness", "capture_format": "2"}, "+ a 1 " + json.dumps("x") + "\n~ b 1 " + quoted, stamp="2026-09-05T10:00:00Z")
        tree, count = fold_witnessed(load_fragments(self.frags))
        self.assertIn('say "hi".txt', tree)
        self.assertEqual(count, 1)

    def test_malformed_json_path_raises_capture_error(self):
        append_fragment(self.frags, "witness", {"kind": "witness", "capture_format": "2"}, '+ b 1 "unclosed', stamp="2026-09-05T10:00:00Z")
        with self.assertRaises(CaptureError):
            fold_witnessed(load_fragments(self.frags))




if __name__ == "__main__":
    unittest.main()
