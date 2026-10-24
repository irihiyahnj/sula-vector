"""Recall: the whole standing list, literal terms, and traces joined at read time."""

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
from render import load_report, render_for_agent

RECALL = TOOLS / "skills" / "recall.py"
S = "2026-03-01T00:00:00Z"


def short(fid: str) -> str:
    return fid.split("--", 1)[0]


class RecallTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="sula-recall-")).resolve()
        self.dir = self.root / "fragments"
        self.dir.mkdir()

    def tearDown(self):
        shutil.rmtree(self.root)

    def add(self, stamp, kind, summary, body="why", **fields):
        fields = {"kind": kind, "summary": summary, **fields}
        return append_fragment(self.dir, f"{kind}-x", fields, body, stamp=stamp).stem

    def recall(self, *query):
        return subprocess.run([sys.executable, str(RECALL), "--project-root", str(self.root), *query],
                              capture_output=True, text=True)

    def test_map_lists_every_standing_record_and_nothing_else(self):
        old = self.add("2026-01-01T00:00:01.000000Z", "decision", "月度交付")
        new = self.add("2026-01-02T00:00:01.000000Z", "correction", "改为双周交付", supersedes=[old])
        self.add("2026-01-02T00:00:02.000000Z", "fact", "合同已签")
        self.add("2026-01-02T00:00:03.000000Z", "goal", "续约", verifier_ref="shell: true")
        self.add("2026-01-02T00:00:04.000000Z", "annotation", "交付主题", refs=[new],
                 tags=["cadence", "节奏"])
        self.add("2026-01-02T00:00:05.000000Z", "rules", "first", body="## 交付\n- 双周交付")
        self.add("2026-01-02T00:00:06.000000Z", "transcript", "问交付", body="UNIQUE_DIALOGUE")
        run = self.recall("--all")
        self.assertEqual(run.returncode, 0, run.stderr)
        lines = run.stdout.splitlines()
        self.assertTrue(lines[0].startswith("# 2 records in force"), lines[0])
        self.assertIn("1 superseded", lines[0])
        self.assertEqual(len(lines), 3)
        self.assertIn("改为双周交付\n", run.stdout)
        self.assertIn("改为双周交付", self.recall("节奏").stdout)
        self.assertNotIn("交付主题", self.recall("节奏").stdout)
        for absent in ("月度交付", "合同已签", "UNIQUE_DIALOGUE", "rules  first"):
            self.assertNotIn(absent, run.stdout)

    def test_topics_are_counted_listed_and_lent_by_annotations(self):
        a = self.add("2026-01-01T00:00:01.000000Z", "decision", "月度交付", topic=["delivery"])
        b = self.add("2026-01-01T00:00:02.000000Z", "pitfall", "交付前先对账")
        self.add("2026-01-01T00:00:03.000000Z", "decision", "办公室搬迁")
        self.add("2026-01-01T00:00:04.000000Z", "annotation", "回填主题", refs=[b], topic=["delivery", "Finance"])
        directory = self.recall().stdout
        self.assertIn("# 2 topics over 3 records in force", directory)
        self.assertRegex(directory, r"\ndelivery  2  newest: 2026-01-01T00-00-02")
        self.assertIn("finance  1", directory)
        self.assertIn("(no topic)  1", directory)
        listed = self.recall("--topic", "delivery").stdout
        self.assertIn("月度交付", listed)
        self.assertIn("交付前先对账  #delivery  #finance", listed)
        self.assertNotIn("办公室搬迁", listed)
        self.assertIn("办公室搬迁", self.recall("--no-topic").stdout)
        self.assertEqual(self.recall("--topic", "delivery", "月度").returncode, 2)
        frags, _ = load_report(self.dir)
        boot = render_for_agent(frags)
        self.assertIn("## Topics (3 records in force; count per topic)\ndelivery 2 · finance 1 · (no topic) 1", boot)
        self.assertIn("topic: delivery, finance", self.recall(short(b)).stdout)
        self.assertIn("topic: delivery", self.recall(short(a)).stdout)

    def test_note_writes_topic_apart_from_tags(self):
        run = subprocess.run([sys.executable, str(TOOLS / "note.py"), str(self.root), "--kind", "decision",
                              "--topic", "4g", "--tags", "蜂窝,lte", "--title", "x", "why"],
                             capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        [path] = self.dir.glob("*.md")
        text = path.read_text(encoding="utf-8")
        self.assertIn('topic: ["4g"]', text)
        self.assertIn('tags: ["蜂窝", "lte"]', text)
        for bad in ("蜂窝", "Cellular", "cellular_4g", "-x"):
            refused = subprocess.run([sys.executable, str(TOOLS / "note.py"), str(self.root), "--kind",
                                      "decision", f"--topic={bad}", "--title", "x", "why"],
                                     capture_output=True, text=True)
            self.assertEqual(refused.returncode, 2, bad)
            self.assertIn("English kebab-case", refused.stderr)

    def test_terms_are_literal_case_blind_and_ranked(self):
        self.add("2026-01-01T00:00:01.000000Z", "decision", "FlClash 只能重启 GUI",
                 body="helper 重启会整机断网")
        self.add("2026-01-01T00:00:02.000000Z", "pitfall", "断网先查 killswitch")
        self.add("2026-01-01T00:00:03.000000Z", "decision", "xzy 不应命中")
        self.add("2026-01-01T00:00:04.000000Z", "transcript", "怎么又断网了", body="## User\n怎么又断网了")
        out = self.recall("断网", "flclash").stdout
        hits = [line for line in out.splitlines() if line.startswith("[")]
        self.assertIn("[2/2 断网,flclash]", hits[0])
        self.assertIn("FlClash 只能重启 GUI", hits[0])
        self.assertIn("[1/2 断网]", hits[1])
        self.assertIn("## transcripts (1)", out)
        self.assertIn("怎么又断网了", out)
        self.assertNotIn("xzy", self.recall("x.y").stdout.split("\n", 1)[1])

    def test_superseded_hit_points_to_what_is_in_force(self):
        old = self.add("2026-01-01T00:00:01.000000Z", "decision", "月度交付")
        mid = self.add("2026-01-02T00:00:01.000000Z", "decision", "改季度", supersedes=[old])
        self.add("2026-01-03T00:00:01.000000Z", "correction", "最终双周", supersedes=[mid])
        out = self.recall("月度").stdout
        self.assertIn("↳ superseded; in force now:", out)
        self.assertIn("最终双周", out)
        self.assertNotIn("改季度", out)

    def test_trace_joins_rules_turn_and_dialogue(self):
        choice = self.add("2026-03-01T00:00:05.000000Z", "decision", "选 A", session=S)
        self.add("2026-03-01T00:00:06.000000Z", "fact", "A 已下单", session=S)
        self.add("2026-03-01T00:00:07.000000Z", "decision", "别的会话", session="2026-03-01T00:00:01Z")
        closing = self.add("2026-03-01T00:00:09.000000Z", "transcript", "要选哪家", session=S,
                           body="## User\n要选哪家")
        self.add("2026-03-01T00:00:10.000000Z", "rules", "first",
                 body="## 采购\n- 采购选 A [2026-03-01T00-00-05.000000Z]\n- 不相干 [2026-02-01T00-00-00Z]")
        out = self.recall(short(choice)).stdout
        self.assertIn("kind: decision (judgment, in force)", out)
        self.assertIn(f"session: {S}", out)
        self.assertIn("cited by the current rules:\n  - 采购选 A", out)
        self.assertNotIn("不相干", out)
        self.assertIn(f"dialogue (same session): {short(closing)}", out)
        self.assertIn("same turn:", out)
        self.assertIn("A 已下单", out)
        self.assertNotIn("别的会话", out)

    def test_unsigned_records_are_traced_by_inference_and_say_so(self):
        old = self.add("2026-01-01T00:00:01.000000Z", "decision", "旧决定")
        closing = self.add("2026-01-01T00:00:30.000000Z", "transcript", "旧对话")
        out = self.recall(short(old)).stdout
        self.assertIn("session: unsigned", out)
        self.assertIn("dialogue (inferred:", out)
        self.assertIn(short(closing), out)

    def test_trace_of_a_transcript_lists_its_turn(self):
        early = self.add("2026-03-01T00:00:01.000000Z", "decision", "上一轮的", session=S)
        self.add("2026-03-01T00:00:02.000000Z", "transcript", "第一轮", session=S)
        self.add("2026-03-01T00:00:03.000000Z", "decision", "这一轮的", session=S)
        closing = self.add("2026-03-01T00:00:04.000000Z", "transcript", "第二轮", session=S)
        out = self.recall(short(closing)).stdout
        self.assertIn("recorded in this turn:", out)
        self.assertIn("这一轮的", out)
        self.assertNotIn("上一轮的", out)
        self.assertIn("上一轮的", self.recall(short(early)).stdout)

    def test_a_partial_prefix_lists_instead_of_tracing(self):
        self.add("2026-04-01T00:00:01.000000Z", "decision", "第一个")
        self.add("2026-04-01T00:00:02.000000Z", "decision", "第二个")
        out = self.recall("2026-04-01T00").stdout
        self.assertTrue(out.startswith("# 2 fragments start with 2026-04-01T00"))
        self.assertNotIn("path:", out)

    def test_bad_queries_fail_loudly(self):
        self.add("2026-04-01T00:00:01.000000Z", "decision", "第一个")
        missing = self.recall("2030-01-01T00")
        self.assertEqual(missing.returncode, 1)
        self.assertIn("no fragment id starts with", missing.stderr)
        mixed = self.recall("2026-04-01T00", "第一个")
        self.assertEqual(mixed.returncode, 2)

    def test_output_is_byte_stable(self):
        self.add("2026-01-01T00:00:01.000000Z", "decision", "甲", tags=["x"])
        self.add("2026-01-01T00:00:02.000000Z", "decision", "乙", session=S)
        for query in ((), ("甲", "乙"), ("2026-01-01T00-00-02",)):
            self.assertEqual(self.recall(*query).stdout, self.recall(*query).stdout)


if __name__ == "__main__":
    unittest.main()
