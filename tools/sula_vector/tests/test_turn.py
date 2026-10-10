"""Closing a turn: verbatim, redacted, local-only transcripts and the receipt."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS))
from append import append_fragment
from render import load_report, render_for_agent, view_doctor, view_journal
from turn import IGNORE_LINE, REDACTED, redact

HAS_GIT = shutil.which("git") is not None


class RedactTest(unittest.TestCase):
    def assertHidden(self, text, secret, kept=""):
        out, count = redact(text)
        self.assertNotIn(secret, out)
        self.assertIn(REDACTED, out)
        self.assertGreaterEqual(count, 1)
        if kept:
            self.assertIn(kept, out)

    def test_token_shapes(self):
        cases = [
            "sk-ant-api03-" + "a1B2" * 10,
            "sk-proj-" + "Z9y8" * 8,
            "ghp_" + "A" * 36,
            "github_pat_" + "11ABCDEFG" * 5,
            "glpat-" + "x" * 20,
            "AKIA" + "ABCDEFGHIJKLMNOP",
            "xoxb-1234567890-abcdefghij",
            "AIza" + "S" * 35,
            "npm_" + "a" * 36,
            "hf_" + "b" * 34,
            "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
        ]
        for secret in cases:
            with self.subTest(secret=secret[:12]):
                self.assertHidden(f"用这个 {secret} 登录", secret, kept="用这个")

    def test_private_key_block(self):
        key = "-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXk\nAAAA\n-----END OPENSSH PRIVATE KEY-----"
        self.assertHidden(f"before\n{key}\nafter", "b3BlbnNzaC1rZXk", kept="after")

    def test_named_values_keep_the_name(self):
        self.assertHidden("export DB_PASSWORD=hunter2hunter", "hunter2hunter", kept="DB_PASSWORD=")
        self.assertHidden('"api_key": "q8f7d6s5a4"', "q8f7d6s5a4", kept='"api_key": "')
        self.assertHidden("client_secret: Zx81-Lm92-Pq", "Zx81-Lm92-Pq", kept="client_secret:")
        self.assertHidden("Authorization: Bearer abc.def-ghi_jkl012", "abc.def-ghi_jkl012",
                          kept="Authorization: Bearer ")
        self.assertHidden("git clone https://jing:s3cr3tpass@example.com/r.git", "s3cr3tpass",
                          kept="https://jing:")

    def test_ordinary_text_is_untouched(self):
        text = (
            "sha256: 0810c38ac6e8d60eaad65887aae0214d8c8d7b3a9218532adb41a8783bc75c35\n"
            "id 2026-10-10T16-00-15.795634Z--correction-e5d4cc8695564f1fa83b7b0f1ca2ceb5\n"
            "max_tokens=1024 and input_tokens: 124000\n"
            "set token=<your token> or PASSWORD=$PASSWORD\n"
            "author: claude-opus-5-5\n"
            "额外成本约为整场会话的 3–10%，token 也不多。\n"
        )
        out, count = redact(text)
        self.assertEqual(out, text)
        self.assertEqual(count, 0)

    def test_count_is_exact(self):
        out, count = redact("token=abcdef123 and sk-" + "k" * 30 + " and secret: 987zyx654")
        self.assertEqual(count, 3)
        self.assertEqual(out.count(REDACTED), 3)


class TurnTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="sula-turn-")).resolve()
        (self.root / "fragments").mkdir()

    def tearDown(self):
        shutil.rmtree(self.root)

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.root), *args], capture_output=True, text=True)

    def turn(self, text, *args):
        return subprocess.run([sys.executable, str(TOOLS / "turn.py"), str(self.root), *args],
                              input=text, capture_output=True, text=True)

    def transcripts(self):
        return sorted((self.root / "fragments").glob(f"*--transcript-*.md"))

    @unittest.skipUnless(HAS_GIT, "git not installed")
    def test_records_verbatim_and_git_never_sees_it(self):
        self.git("init", "-q")
        dialogue = "## User\n能存吗？api_key=abc123secret\n\n## Reply\n可以，只在本机。"
        run = self.turn(dialogue)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("[sula] turn recorded", run.stdout)
        self.assertIn("1 secret(s) redacted", run.stdout)
        [path] = self.transcripts()
        body = path.read_text(encoding="utf-8")
        self.assertIn("可以，只在本机。", body)
        self.assertNotIn("abc123secret", body)
        self.assertIn(IGNORE_LINE, (self.root / ".gitignore").read_text(encoding="utf-8"))
        self.git("add", "-A")
        tracked = self.git("ls-files").stdout
        self.assertNotIn("transcript", tracked)
        self.assertIn(".gitignore", tracked)

    @unittest.skipUnless(HAS_GIT, "git not installed")
    def test_ignore_line_written_once(self):
        self.git("init", "-q")
        (self.root / ".gitignore").write_text("node_modules", encoding="utf-8")
        self.assertEqual(self.turn("one").returncode, 0)
        self.assertEqual(self.turn("two").returncode, 0)
        text = (self.root / ".gitignore").read_text(encoding="utf-8")
        self.assertEqual(text.count(IGNORE_LINE), 1)
        self.assertTrue(text.startswith("node_modules\n"))
        self.assertEqual(len(self.transcripts()), 2)

    @unittest.skipUnless(HAS_GIT, "git not installed")
    def test_refuses_when_git_would_track_it(self):
        self.git("init", "-q")
        (self.root / ".gitignore").write_text(f"{IGNORE_LINE}\n!fragments/*\n", encoding="utf-8")
        run = self.turn("secret plans")
        self.assertEqual(run.returncode, 2)
        self.assertIn("turn NOT recorded", run.stderr)
        self.assertEqual(self.transcripts(), [])

    def test_works_without_git_and_prepares_ignore(self):
        run = self.turn("no repository here")
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("no git", run.stdout)
        self.assertIn(IGNORE_LINE, (self.root / ".gitignore").read_text(encoding="utf-8"))
        self.assertEqual(len(self.transcripts()), 1)

    def test_empty_input_is_refused(self):
        run = self.turn("   \n")
        self.assertEqual(run.returncode, 2)
        self.assertEqual(self.transcripts(), [])

    def test_since_shows_judgments_not_transcripts(self):
        append_fragment(self.root / "fragments", "decision-x",
                        {"kind": "decision", "summary": "选了 A"}, "why")
        run = self.turn("## User\nhi\n## Reply\nhello", "--since", "2000-01-01T00:00:00Z")
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("[sula] +1 this turn:", run.stdout)
        self.assertIn("选了 A", run.stdout)
        self.assertNotIn("transcript ", run.stdout.split("\n", 1)[1])

    def test_views_leave_transcripts_out(self):
        append_fragment(self.root / "fragments", "decision-x",
                        {"kind": "decision", "summary": "选了 A"}, "why")
        self.assertEqual(self.turn("## User\nUNIQUE_DIALOGUE_TEXT\n## Reply\nok").returncode, 0)
        frags, problems = load_report(self.root / "fragments")
        self.assertTrue(view_doctor(frags, problems)["ok"])
        boot = render_for_agent(frags)
        self.assertNotIn("UNIQUE_DIALOGUE_TEXT", boot)
        self.assertIn("1 transcript fragments", boot)
        self.assertIn("Fragments: 1,", boot)
        days = view_journal(frags)
        self.assertEqual([e["kind"] for d in days for e in d["evidence"]], [])
        mark = subprocess.run([sys.executable, str(TOOLS / "render.py"), str(self.root),
                               "--view", "changes-summary", "--since", "2000-01-01T00:00:00Z"],
                              capture_output=True, text=True).stdout
        self.assertIn("[sula] +1 this turn:", mark)

    def test_note_refuses_transcripts(self):
        run = subprocess.run([sys.executable, str(TOOLS / "note.py"), str(self.root),
                              "--kind", "transcript", "text"], capture_output=True, text=True)
        self.assertEqual(run.returncode, 2)
        self.assertIn("turn.py", run.stderr)


if __name__ == "__main__":
    unittest.main()
