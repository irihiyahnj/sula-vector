"""Rule sheet: the boot carries rules, changes are one line, history is kept."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS))
from append import append_fragment  # noqa: E402
from migrate import GIT_HOOK_MARKER, RETIRED_FILES, install_tooling, retire_capture_triggers  # noqa: E402
from render import load_fragments, load_report, render_for_agent, rules_heads, view_doctor  # noqa: E402

SHEET = "## 部署\n- 只从 main 分支部署 [2026-01-01T00-00-00Z]\n- 生产 MAX_HOPS=8，改动须 Owner 拍板\n\n## 提交\n- 只用显式 pathspec 提交，禁止 git add -A\n"


class RulesCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="sula-rules-"))
        self.frags = self.root / "fragments"
        self.frags.mkdir()

    def tearDown(self):
        shutil.rmtree(self.root)

    def tool(self, name, *args, stdin=None):
        return subprocess.run([sys.executable, str(TOOLS / name), str(self.root), *args],
                              capture_output=True, text=True, input=stdin)

    def rules(self, *args):
        return self.tool("rules.py", *args)

    def set_sheet(self, text=SHEET):
        source = self.root / "sheet.md"
        source.write_text(text, encoding="utf-8")
        result = self.rules("set", "--from", str(source), "--why", "first sheet")
        self.assertEqual(result.returncode, 0, result.stderr)

    def sheet(self):
        heads = rules_heads(load_fragments(self.frags))
        self.assertEqual(len(heads), 1)
        return heads[0].body.splitlines()

    def count(self):
        return len(list(self.frags.glob("*--rules-*.md")))


class TestSheetLifecycle(RulesCase):
    def test_boot_carries_the_rules_not_judgment_titles(self):
        append_fragment(self.frags, "decision", {"kind": "decision", "summary": "an event title"}, "body")
        self.set_sheet()
        boot = render_for_agent(load_fragments(self.frags))
        self.assertIn("- 只用显式 pathspec 提交，禁止 git add -A", boot)
        self.assertIn("## Recent judgments", boot)
        self.assertNotIn("## Judgments in force", boot)

    def test_without_a_sheet_boot_falls_back_and_says_so(self):
        append_fragment(self.frags, "decision", {"kind": "decision", "summary": "an event title"}, "body")
        boot = render_for_agent(load_fragments(self.frags))
        self.assertIn("no rule sheet yet", boot)
        self.assertIn("an event title", boot)

    def test_edit_changes_exactly_one_line_and_supersedes(self):
        self.set_sheet()
        before = self.sheet()
        result = self.rules("edit", "--match", "MAX_HOPS=8", "--why", "Owner raised it", "生产 MAX_HOPS=10，改动须 Owner 拍板")
        self.assertEqual(result.returncode, 0, result.stderr)
        after = self.sheet()
        changed = [i for i, (a, b) in enumerate(zip(before, after)) if a != b]
        self.assertEqual(len(before), len(after))
        self.assertEqual(changed, [2])
        self.assertEqual(after[2], "- 生产 MAX_HOPS=10，改动须 Owner 拍板")
        self.assertIn("-- 生产 MAX_HOPS=8", result.stdout)
        self.assertEqual(self.count(), 2)
        self.assertTrue(view_doctor(*load_report(self.frags))["ok"])

    def test_add_into_existing_and_new_sections(self):
        self.set_sheet()
        self.assertEqual(self.rules("add", "--section", "部署", "--why", "w", "部署后盯日志").returncode, 0)
        lines = self.sheet()
        self.assertEqual(lines.index("- 部署后盯日志"), 3)
        self.assertEqual(self.rules("add", "--section", "安全", "--why", "w", "- 密钥不进仓库").returncode, 0)
        self.assertEqual(self.sheet()[-2:], ["## 安全", "- 密钥不进仓库"])

    def test_remove_drops_one_line(self):
        self.set_sheet()
        before = self.sheet()
        self.assertEqual(self.rules("remove", "--match", "只从 main", "--why", "w").returncode, 0)
        after = self.sheet()
        self.assertEqual([line for line in before if line not in after], [before[1]])

    def test_every_write_needs_a_reason(self):
        self.set_sheet()
        result = self.rules("add", "--section", "部署", "x")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.count(), 1)

    def test_ambiguous_or_missing_match_writes_nothing(self):
        self.set_sheet()
        self.assertEqual(self.rules("remove", "--match", "Owner 不存在", "--why", "w").returncode, 2)
        self.assertEqual(self.rules("edit", "--match", "- ", "--why", "w", "x").returncode, 2)
        self.assertEqual(self.count(), 1)

    def test_malformed_and_duplicate_sheets_are_refused(self):
        source = self.root / "bad.md"
        source.write_text("## A\nloose text\n", encoding="utf-8")
        self.assertEqual(self.rules("set", "--from", str(source), "--why", "w").returncode, 2)
        source.write_text("## A\n- same\n- same\n", encoding="utf-8")
        self.assertEqual(self.rules("set", "--from", str(source), "--why", "w").returncode, 2)
        self.assertEqual(self.count(), 0)

    def test_unchanged_sheet_appends_nothing(self):
        self.set_sheet()
        source = self.root / "sheet.md"
        result = self.rules("set", "--from", str(source), "--why", "again")
        self.assertIn("unchanged", result.stdout)
        self.assertEqual(self.count(), 1)

    def test_mangled_text_is_refused_cleanly(self):
        self.set_sheet()
        result = subprocess.run([sys.executable, str(TOOLS / "rules.py"), str(self.root), "add",
                                 "--section", "部署", "--why", "w", b"bad \xef\xbc rule"],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("not valid UTF-8", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(self.count(), 1)

    def test_line_edits_need_a_sheet(self):
        self.assertEqual(self.rules("add", "--section", "A", "--why", "w", "x").returncode, 2)

    def test_note_refuses_to_write_a_sheet(self):
        result = self.tool("note.py", "--kind", "rules", "- x")
        self.assertEqual(result.returncode, 2)

    def test_log_lists_every_version_with_its_reason(self):
        self.set_sheet()
        self.rules("remove", "--match", "只从 main", "--why", "branch rule retired")
        out = self.rules("log").stdout
        self.assertIn("first sheet", out)
        self.assertIn("+0 -1  branch rule retired", out)


class TestFork(RulesCase):
    def test_fork_is_reported_shown_and_merged(self):
        self.set_sheet()
        parent = rules_heads(load_fragments(self.frags))[0].id
        for text in ("## A\n- one\n", "## A\n- two\n"):
            append_fragment(self.frags, "rules", {"kind": "rules", "supersedes": [parent], "summary": "concurrent"}, text)
        report = view_doctor(*load_report(self.frags))
        self.assertIn("rules-fork", report["by_code"])
        boot = render_for_agent(load_fragments(self.frags))
        self.assertIn("- one", boot)
        self.assertIn("- two", boot)
        self.assertEqual(self.rules("add", "--section", "A", "--why", "w", "three").returncode, 2)
        self.set_sheet("## A\n- one\n- two\n")
        self.assertTrue(view_doctor(*load_report(self.frags))["ok"])
        self.assertEqual(self.sheet(), ["## A", "- one", "- two"])


class TestUpdateRetiresOldTooling(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="sula-retire-"))

    def tearDown(self):
        shutil.rmtree(self.root)

    def test_retired_files_and_our_triggers_are_removed(self):
        target = self.root / "tools" / "sula_vector"
        for rel in RETIRED_FILES:
            (target / rel).parent.mkdir(parents=True, exist_ok=True)
            (target / rel).write_text("old", encoding="utf-8")
        (target / "principles" / "2026-05-23T04-50-00Z--principle-tier-A-highest-rule.md").write_text("old", encoding="utf-8")
        result = install_tooling(self.root, TOOLS)
        self.assertEqual(result["retired"], len(RETIRED_FILES) + 1)
        self.assertFalse((target / "principles").exists())
        for rel in RETIRED_FILES:
            self.assertFalse((target / rel).exists(), rel)
        self.assertFalse((target / "hooks").exists())
        self.assertTrue((target / "rules.py").is_file())

        hooks = self.root / ".git" / "hooks"
        hooks.mkdir(parents=True)
        (hooks / "post-commit").write_text(
            "#!/bin/sh\necho mine\n" + GIT_HOOK_MARKER + "\n"
            'python3 "$(git rev-parse --show-toplevel)/tools/sula_vector/skills/witness.py" \\\n'
            '  --project-root "$(git rev-parse --show-toplevel)" >/dev/null 2>&1 || true\n',
            encoding="utf-8")
        kiro = self.root / ".kiro" / "agents"
        kiro.mkdir(parents=True)
        (kiro / "sula.json").write_text('{"x": "tools/sula_vector/skills/finish.py"}', encoding="utf-8")
        retire_capture_triggers(self.root)
        self.assertEqual((hooks / "post-commit").read_text(encoding="utf-8"), "#!/bin/sh\necho mine\n")
        self.assertFalse((kiro / "sula.json").exists())

    def test_previous_generated_pointer_is_refreshed_custom_is_kept(self):
        from migrate import _v13_pointer_text, install_host_pointers
        (self.root / "CLAUDE.md").write_text(_v13_pointer_text("CLAUDE.md"), encoding="utf-8")
        (self.root / "GEMINI.md").write_text("# our own rules\n", encoding="utf-8")
        install_host_pointers(self.root)
        self.assertIn("rules.py", (self.root / "CLAUDE.md").read_text(encoding="utf-8"))
        self.assertEqual((self.root / "GEMINI.md").read_text(encoding="utf-8"), "# our own rules\n")


if __name__ == "__main__":
    unittest.main(verbosity=2)
