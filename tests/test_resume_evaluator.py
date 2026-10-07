"""Offline integration checks: one batch, full evidence, safe local output."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import sys
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import evaluate_tech_resume as evaluator


RESUME = """Example Candidate
Backend engineer
contact@example.invalid | +1 (555) 123-4567 | https://example.invalid/profile
Experience
- Implemented Python queue workers with idempotency keys; reduced duplicate jobs by 80%.
  Added retry tests and production dashboards.
- Responsible for APIs.
Skills: Python, PostgreSQL
"""
JOB = """Backend engineer
- Build reliable Python services and operate PostgreSQL.
- Experience with Kubernetes.
We offer flexible schedules.
"""


class RecordingClient:
    def __init__(self, selections=None):
        self.calls = []
        self.selections = {"estimated_role": "backend", "estimated_level": "mid", **(selections or {})}

    def system_one(self, **request):
        self.calls.append(request)
        answers = {}
        for key, spec in request["questions"].items():
            if spec["type"] == "noul":
                answers[key] = {"type": "noul", "noul": 0.5}
            elif spec["type"] == "score":
                answers[key] = {"type": "score", "score": 2.0, "confidence": 0.0,
                                "probabilities": {str(i): 0.2 for i in range(5)}}
            else:
                selected = self.selections.get(key)
                if selected is None:
                    selected = "outcome" if key.endswith("_edit") else (
                        "partial" if key.startswith("requirement_") else "impact")
                answers[key] = {"type": "choice", "choice": selected, "confidence": 1.0,
                                "probabilities": {item: float(item == selected) for item in spec["criteria"]}}
        result = {"model": "offline-test", "answers": answers, "usage": {"calls": 1}}
        return SimpleNamespace(raw_http_response=SimpleNamespace(json=lambda: result))


class ResumeEvaluatorTests(unittest.TestCase):
    def test_script_can_be_launched_directly(self):
        script = Path(evaluator.__file__)
        result = subprocess.run([str(script), "--help"], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Evaluate a tech resume", result.stdout)

    def test_missing_targets_estimated_independently_and_supplied_targets_preserved(self):
        for role, level in ((None, None), ("security", None), (None, "senior"), ("backend", "mid-level")):
            with self.subTest(role=role, level=level):
                built, scope = evaluator.build_evaluation(RESUME, job=JOB, role=role, level=level)
                client = RecordingClient()
                result = evaluator.executeJevRequest(built, client=client)
                report = evaluator.make_report(built, scope, result)
                self.assertEqual(len(client.calls), 1)
                self.assertEqual(report["target"], {"role": role, "level": level})
                for axis, value in (("role", role), ("level", level)):
                    self.assertEqual("estimated_" + axis in built["request"]["questions"], value is None)
                    self.assertEqual(axis in report["target_estimates"], value is None)
                    if value is None:
                        estimate = report["target_estimates"][axis]
                        self.assertEqual(estimate["probabilities"], result["answers"]["estimated_" + axis]["probabilities"])
                        self.assertIn("Estimated " + axis, evaluator.markdown(report))
                self.assertEqual(client.calls[0]["state"]["target"], {"role": role, "level": level})

    def test_estimates_can_abstain_without_fabricated_defaults(self):
        built, scope = evaluator.build_evaluation("Technical work; scope unclear.")
        client = RecordingClient({"estimated_role": "insufficient_evidence", "estimated_level": "insufficient_evidence"})
        result = evaluator.executeJevRequest(built, client=client)
        report = evaluator.make_report(built, scope, result)
        self.assertIsNone(report["target"]["role"])
        self.assertIsNone(report["target"]["level"])
        self.assertIn("Insufficient evidence to estimate a role", evaluator.markdown(report))
        self.assertIn("Insufficient evidence to estimate a level", evaluator.markdown(report))
        self.assertEqual(report["target_estimates"]["role"]["choice"], "insufficient_evidence")

    def test_single_validated_batch_and_complete_report(self):
        built, scope = evaluator.build_evaluation(RESUME, job=JOB, role="backend", level="mid-level")
        client = RecordingClient()
        result = evaluator.executeJevRequest(built, client=client)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(client.calls[0], built["request"])
        self.assertGreater(len(result["answers"]), 30)
        report = evaluator.make_report(built, scope, result)
        output = evaluator.markdown(report)
        self.assertIn("reduced duplicate jobs by 80%", output)
        self.assertIn("P(enough context)", output)
        self.assertIn("0: 20.0%; 1: 20.0%; 2: 20.0%; 3: 20.0%; 4: 20.0%", output)
        self.assertIn("Some relevant evidence exists", output)
        self.assertIn(built["request_sha256"], output)
        self.assertEqual(json.loads(json.dumps(report))["result"], result)
        state = json.dumps(built["request"]["state"])
        self.assertNotIn("contact@example.invalid", state)
        self.assertNotIn("555", state)
        self.assertNotIn("https://example.invalid", state)
        self.assertIn("Added retry tests", state)

    def test_limits_do_not_truncate_shared_evidence(self):
        built, scope = evaluator.build_evaluation(RESUME, job=JOB, max_bullets=1, max_job_lines=1)
        self.assertEqual(scope["bullets_not_individually_reviewed"], 1)
        self.assertEqual(scope["job_lines_not_individually_reviewed"], 3)
        state = built["request"]["state"]
        self.assertIn("Responsible for APIs", json.dumps(state))
        self.assertIn("Kubernetes", json.dumps(state))
        self.assertNotIn("bullet_7", built["request"]["questions"])
        self.assertNotIn("requirement_3", built["request"]["questions"])

    def test_invalid_and_oversized_inputs_fail_before_network(self):
        for kwargs in ({"resume": " "}, {"resume": RESUME, "job": " "},
                       {"resume": RESUME, "role": " "}, {"resume": RESUME, "level": ""},
                       {"resume": RESUME, "max_bullets": -1}, {"resume": "x" * 70000}):
            with self.subTest(kwargs=list(kwargs)):
                with self.assertRaises(evaluator.ResumeInputError):
                    evaluator.build_evaluation(**kwargs)
        built, _ = evaluator.build_evaluation(RESUME)
        built["request"]["state"]["target"]["role"] = "tampered"
        client = RecordingClient()
        with self.assertRaises(ValueError):
            evaluator.executeJevRequest(built, client=client)
        self.assertEqual(client.calls, [])

    def test_full_default_line_limits_fit_request_budget(self):
        built, scope = evaluator.build_evaluation(
            "Backend engineer\n" + "- Built Python services with retry tests and measured outcomes.\n" * 20,
            job="- Build Python services and operate PostgreSQL.\n" * 30)
        self.assertEqual(len(scope["bullets_reviewed"]), 20)
        self.assertEqual(len(scope["job_lines_reviewed"]), 30)
        self.assertLessEqual(built["sizes"]["questions_bytes"], 48 * 1024)
        self.assertLessEqual(built["sizes"]["request_bytes"], 64 * 1024)

    def test_docx_paragraphs_and_list_markers(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "resume.docx"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("word/document.xml", '''<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Engineer</w:t></w:r></w:p><w:p><w:pPr><w:numPr><w:numId w:val="1"/></w:numPr></w:pPr><w:r><w:t>Built </w:t></w:r><w:r><w:t>services.</w:t></w:r></w:p></w:body></w:document>''')
            self.assertEqual(evaluator.read_document(path), "Engineer\n- Built services.")

    def test_pdf_extraction_and_empty_scan(self):
        with patch.object(evaluator.shutil, "which", return_value="/usr/bin/pdftotext"), \
             patch.object(evaluator.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout=b"Engineer\n- Built services.")) as run:
            self.assertIn("Built services", evaluator.read_document(Path("resume.pdf")))
            self.assertEqual(run.call_args.args[0][0], "pdftotext")
        with patch.object(evaluator.shutil, "which", return_value=None):
            with self.assertRaisesRegex(evaluator.ResumeInputError, "pdftotext"):
                evaluator.read_document(Path("resume.pdf"))
        with patch.object(evaluator.shutil, "which", return_value="pdftotext"), \
             patch.object(evaluator.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout=b"\n\f")):
            with self.assertRaisesRegex(evaluator.ResumeInputError, "OCR"):
                evaluator.read_document(Path("resume.pdf"))

    def test_cli_report_uses_one_real_executor_batch(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "resume.txt"
            source.write_text(RESUME, encoding="utf-8")
            client = RecordingClient()
            executor = evaluator.executeJevRequest
            with patch.dict(evaluator.os.environ, {"TYPESAFE_API_KEY": "test-only"}), \
                 patch.object(evaluator, "executeJevRequest", side_effect=lambda built, **kw: executor(built, client=client, **kw)), \
                 redirect_stdout(io.StringIO()) as stdout:
                self.assertEqual(evaluator.main([str(source), "--format", "json"]), 0)
            self.assertEqual(len(client.calls), 1)
            report = json.loads(stdout.getvalue())
            self.assertNotIn("job_skills", report["questions"])
            self.assertEqual(report["result"]["model"], "offline-test")

    def test_cli_dry_run_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory) / "resume.md", Path(directory) / "report.json"
            source.write_text(RESUME, encoding="utf-8")
            with patch.object(evaluator, "executeJevRequest") as send:
                self.assertEqual(evaluator.main([str(source), "--dry-run", "--output", str(output)]), 0)
                send.assert_not_called()
            preview = json.loads(output.read_text())
            self.assertIsNone(preview["built"]["request"]["state"]["target"]["role"])
            self.assertIn("estimated_role", preview["built"]["request"]["questions"])
            self.assertIn("estimated_level", preview["built"]["request"]["questions"])
            original = output.read_bytes()
            with redirect_stderr(io.StringIO()):
                self.assertEqual(evaluator.main([str(source), "--dry-run", "--output", str(output)]), 1)
            self.assertEqual(output.read_bytes(), original)
            with patch.dict(evaluator.os.environ, {"TYPESAFE_API_KEY": "test-only"}), \
                 patch.object(evaluator, "executeJevRequest", side_effect=RuntimeError("private payload")), \
                 redirect_stderr(io.StringIO()) as error, redirect_stdout(io.StringIO()) as stdout:
                self.assertEqual(evaluator.main([str(source)]), 1)
                self.assertNotIn("private payload", error.getvalue())
                self.assertEqual(stdout.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
