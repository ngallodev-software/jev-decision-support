"""Offline contract check: real SDK, mocked HTTP, no credentials or network."""

import io
import json
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

import httpx2
from typesafe_sdk import RetryPolicy, TypeSafeAPIError, TypeSafeClient

import jev_decision
from jev_decision import (
    buildJevRequest,
    executeJevRequest,
    makeJevDecision,
    makeJevDecisions,
    rebuildJevRequest,
)


class DecisionCheck(unittest.TestCase):
    def setUp(self):
        self.requests = []
        self.status = 200
        self.answer = {"type": "choice", "choice": "reuse", "confidence": 0.8,
                       "probabilities": {"reuse": 0.9, "replace": 0.1}}

        def handle(request):
            self.requests.append(json.loads(request.content))
            self.assertEqual(request.url.path, "/v1/systemone")
            return httpx2.Response(self.status, json={
                "model": "fixture", "answers": {"decision": self.answer},
                "usage": {"input_tokens": 12, "output_tokens": 4},
            })

        self.client = TypeSafeClient(api_key="offline-test", base_url="https://fixture.invalid",
                                     transport=httpx2.MockTransport(handle),
                                     retry=RetryPolicy(max_retries=0))
        self.addCleanup(self.client.close)

    def call(self, **kwargs):
        return makeJevDecision({"fact": "existing helper"}, "Which option fits?",
                               client=self.client, **kwargs)

    def test_primitives_and_request_contract(self):
        result = self.call(acceptable_answers=["reuse", "replace"], model="jev-latest")
        self.assertEqual(result["answers"]["decision"], self.answer)
        self.assertEqual(result["usage"]["input_tokens"], 12)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.requests[0], {
            "state": {"fact": "existing helper"}, "model": "jev-latest",
            "questions": {"decision": {"type": "choice", "instructions": "Which option fits?",
                                       "criteria": {"reuse": None, "replace": None}}},
        })
        self.call(acceptable_answers={"reuse": "Extend", "replace": "Replace"})
        self.assertEqual(self.requests[-1]["questions"]["decision"]["criteria"],
                         {"reuse": "Extend", "replace": "Replace"})
        self.answer = {"type": "noul", "noul": 0.7}
        self.assertEqual(self.call(kind="noul")["answers"]["decision"]["noul"], 0.7)
        self.answer = {"type": "score", "score": 0.25, "confidence": 0.5,
                       "probabilities": {"0": 0.75, "1": 0.25},
                       "legend": {"0": "low", "1": "high"}}
        self.assertEqual(self.call(kind="score", acceptable_answers=["low", "high"])
                         ["answers"]["decision"]["legend"], {"0": "low", "1": "high"})

    def test_input_rejected_before_network(self):
        for kwargs in [
            {"acceptable_answers": []}, {"acceptable_answers": ["a", "a"]},
            {"acceptable_answers": ["a", 2]}, {"acceptable_answers": {"": None, "b": None}},
            {"kind": "score", "acceptable_answers": ["one"]},
            {"kind": "noul", "acceptable_answers": ["yes", "no"]}, {"kind": "bogus"},
        ]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.call(**kwargs)
        for context, question in [("x", " "), ({"n": float("nan")}, "x"), ("x" * 65536, "x")]:
            with self.assertRaises(ValueError):
                makeJevDecision(context, question, ["a", "b"], client=self.client)
        self.assertEqual(self.requests, [])

    def test_deterministic_request_builder_hashes_and_revisions(self):
        questions = {
            "best": {
                "type": "choice",
                "instructions": "Which option best fits the evidence?",
                "criteria": {
                    "reuse": "Extend the helper",
                    "replace": "Replace the helper",
                    "insufficient_evidence": "Need more evidence",
                },
            },
            "supported": {
                "type": "noul",
                "instructions": "Is the evidence sufficient to choose?",
                "criteria": {
                    "true": "The supplied evidence is sufficient",
                    "false": "Material evidence is still missing",
                },
            },
        }
        first = buildJevRequest(
            {"requirement": "Preserve compatibility", "evidence": ["existing helper"]},
            questions,
            model="jev-latest",
            purpose="Choose between bounded alternatives.",
        )
        same = buildJevRequest(
            {"requirement": "Preserve compatibility", "evidence": ["existing helper"]},
            questions,
            model="jev-latest",
            purpose="Choose between bounded alternatives.",
        )
        self.assertEqual(first["request_sha256"], same["request_sha256"])
        self.assertEqual(first["decision_sha256"], same["decision_sha256"])
        self.assertEqual(len(first["request_sha256"]), 64)
        self.assertGreater(first["sizes"]["state_bytes"], 0)
        self.assertGreater(first["sizes"]["questions_bytes"], 0)

        with self.assertRaisesRegex(ValueError, "semantically unchanged"):
            rebuildJevRequest(
                first,
                {"requirement": "Preserve compatibility", "evidence": ["existing helper"]},
                questions,
                model="jev-latest",
                purpose="Choose between bounded alternatives.",
                change_reason="No actual evidence change.",
            )

        revised = rebuildJevRequest(
            first,
            {
                "requirement": "Preserve compatibility",
                "evidence": ["existing helper", "migration test passed"],
            },
            questions,
            model="jev-latest",
            purpose="Choose between bounded alternatives.",
            change_reason="Added migration-test evidence.",
        )
        self.assertNotEqual(revised["decision_sha256"], first["decision_sha256"])
        self.assertEqual(
            revised["revision"]["previous_decision_sha256"],
            first["decision_sha256"],
        )
        self.assertEqual(
            revised["revision"]["change_reason"],
            "Added migration-test evidence.",
        )

    def test_execute_built_request_rejects_post_validation_mutation(self):
        built = buildJevRequest(
            {"fact": "existing helper"},
            {
                "decision": {
                    "type": "choice",
                    "instructions": "Which option fits?",
                    "criteria": {"reuse": "Extend", "replace": "Replace"},
                }
            },
            model="jev-latest",
        )
        result = executeJevRequest(built, client=self.client)
        self.assertEqual(result["answers"]["decision"], self.answer)
        self.assertEqual(self.requests[-1], built["request"])

        tampered = json.loads(json.dumps(built))
        tampered["request"]["state"]["fact"] = "changed after validation"
        with self.assertRaisesRegex(ValueError, "changed after validation"):
            executeJevRequest(tampered, client=self.client)

    def test_builder_rejects_empty_context_and_invalid_revision_metadata(self):
        questions = {
            "supported": {
                "type": "noul",
                "instructions": {"task": "Is the supplied evidence sufficient?"},
            }
        }
        for context in ("", {}, []):
            with self.subTest(context=context), self.assertRaises(ValueError):
                buildJevRequest(context, questions)
        with self.assertRaisesRegex(ValueError, "change_reason"):
            buildJevRequest("evidence", questions, change_reason="changed")
        with self.assertRaisesRegex(ValueError, "lowercase SHA-256"):
            buildJevRequest(
                "evidence",
                questions,
                previous_decision_sha256="not-a-hash",
                change_reason="changed evidence",
            )

    def test_two_decimal_rounding_accepted(self):
        # Observed live: four options rounded to two decimals summing to 0.99.
        options = ["ready", "ready_minor", "needs_changes", "insufficient_evidence"]
        self.answer = {"type": "choice", "choice": "ready", "confidence": 0.41,
                       "probabilities": {"ready_minor": 0.23, "insufficient_evidence": 0.0,
                                         "ready": 0.56, "needs_changes": 0.2}}
        self.assertEqual(self.call(acceptable_answers=options)["answers"]["decision"]["choice"], "ready")
        self.answer["probabilities"] = {"ready_minor": 0.23, "insufficient_evidence": 0.0,
                                        "ready": 0.5, "needs_changes": 0.2}
        with self.assertRaises(ValueError):
            self.call(acceptable_answers=options)

    def test_bad_answers_and_service_failure(self):
        original = self.answer.copy()
        for changes in [{"choice": "unlisted"}, {"confidence": 2},
                        {"probabilities": {"reuse": 0.6, "replace": 0.1}},
                        {"probabilities": {"reuse": 0.9, "unknown": 0.1}},
                        {"type": "noul", "noul": 0.8}]:
            self.answer = {**original, **changes}
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.call(acceptable_answers=["reuse", "replace"])
        self.status = 401
        with self.assertRaises(TypeSafeAPIError):
            self.call(acceptable_answers=["reuse", "replace"])
        self.status = 200
        self.answer = {"type": "noul", "noul": 1.1}
        with self.assertRaises(ValueError):
            self.call(kind="noul")
        self.answer = {"type": "score", "score": 2, "confidence": 0.5,
                       "probabilities": {"0": 0.5, "1": 0.5},
                       "legend": {"0": "low", "1": "high"}}
        with self.assertRaises(ValueError):
            self.call(kind="score", acceptable_answers=["low", "high"])

    def test_cli_json_and_private_error_handling(self):
        request = {"context": "x", "question": "Which?", "acceptable_answers": ["reuse", "replace"]}
        original = makeJevDecision

        def inject(**kwargs):
            return original(**kwargs, client=self.client)

        output = io.StringIO()
        with patch.object(jev_decision, "makeJevDecision", side_effect=inject), \
                patch("sys.argv", ["jev_decision.py"]), \
                patch("sys.stdin", io.StringIO(json.dumps(request))), redirect_stdout(output):
            self.assertEqual(jev_decision.main(), 0)
        self.assertEqual(json.loads(output.getvalue())["model"], "fixture")
        errors = io.StringIO()
        with patch.object(jev_decision, "makeJevDecision", side_effect=RuntimeError("PRIVATE BODY")), \
                patch("sys.argv", ["jev_decision.py"]), \
                patch("sys.stdin", io.StringIO(json.dumps(request))), redirect_stderr(errors):
            self.assertEqual(jev_decision.main(), 1)
        self.assertEqual(json.loads(errors.getvalue()), {"status": "error", "error_type": "RuntimeError"})
        self.assertNotIn("PRIVATE", errors.getvalue())

    def test_missing_or_malformed_answer_data(self):
        for body in [None, [], {}, {"answers": []}, {"answers": {}},
                     {"answers": {"decision": []}}]:
            response = SimpleNamespace(raw_http_response=httpx2.Response(200, content=json.dumps(body)))
            with self.subTest(body=body), \
                    patch.object(self.client, "system_one", return_value=response), \
                    self.assertRaisesRegex(ValueError, "missing or malformed"):
                self.call(acceptable_answers=["reuse", "replace"])


class BatchCheck(unittest.TestCase):
    QUESTIONS = {
        "best": {"type": "choice", "instructions": "Which fits?",
                 "criteria": {"reuse": "Extend", "replace": "Replace"}},
        "supported": {"type": "noul", "instructions": "Is the claim supported?"},
        "risk": {"type": "score", "instructions": "How risky?", "criteria": ["low", "high"]},
    }

    def setUp(self):
        self.requests = []
        self.answers = {
            "best": {"type": "choice", "choice": "reuse", "confidence": 0.8,
                     "probabilities": {"reuse": 0.9, "replace": 0.1}},
            "supported": {"type": "noul", "noul": 0.7},
            "risk": {"type": "score", "score": 0.25, "confidence": 0.5,
                     "probabilities": {"0": 0.75, "1": 0.25}, "legend": {"0": "low", "1": "high"}},
        }

        def handle(request):
            self.requests.append(json.loads(request.content))
            return httpx2.Response(200, json={"model": "fixture", "answers": self.answers,
                                              "usage": {"input_tokens": 1, "output_tokens": 1}})

        self.client = TypeSafeClient(api_key="offline-test", base_url="https://fixture.invalid",
                                     transport=httpx2.MockTransport(handle),
                                     retry=RetryPolicy(max_retries=0))
        self.addCleanup(self.client.close)

    def call(self, questions=None, context="evidence"):
        return makeJevDecisions(context, self.QUESTIONS if questions is None else questions,
                                client=self.client)

    def test_batch_single_request(self):
        result = self.call()
        self.assertEqual(result["answers"], self.answers)
        self.assertEqual(result["model"], "fixture")
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.requests[0]["questions"], self.QUESTIONS)
        self.assertEqual(self.requests[0]["state"], "evidence")

    def test_batch_bad_answers(self):
        original = {k: dict(v) for k, v in self.answers.items()}
        for name, changes in [("missing", None), ("best", {"type": "noul", "noul": 0.5}),
                              ("best", {"probabilities": {"reuse": 0.6, "replace": 0.1}}),
                              ("best", {"choice": "unlisted"}), ("supported", {"noul": 2}),
                              ("risk", {"score": 5})]:
            self.answers = {k: dict(v) for k, v in original.items()}
            if changes is None:
                del self.answers["risk"]
            else:
                self.answers[name].update(changes)
            with self.subTest(name=name, changes=changes), self.assertRaises(ValueError):
                self.call()

    def test_batch_input_rejected_before_network(self):
        bad = [{}, [], {"": {"type": "noul", "instructions": "x"}}, {"q": "x"},
               {"q": {"type": "noul", "instructions": " "}},
               {"q": {"type": "bogus", "instructions": "x"}},
               {"q": {"type": "choice", "instructions": "x", "criteria": ["only"]}},
               {"q": {"type": "noul", "instructions": "x", "criteria": ["a", "b"]}}]
        for questions in bad:
            with self.subTest(questions=questions), self.assertRaises(ValueError):
                self.call(questions)
        with self.assertRaises(ValueError):
            self.call(context="x" * 65536)
        self.assertEqual(self.requests, [])

    def test_missing_api_key_fails_before_network(self):
        env = {k: v for k, v in os.environ.items() if k != "TYPESAFE_API_KEY"}
        with patch.dict(os.environ, env, clear=True), \
                patch("typesafe_sdk.TypeSafeClient") as owned:
            for call in (lambda: makeJevDecision("x", "Which?", ["a", "b"]),
                         lambda: makeJevDecisions("x", BatchCheck.QUESTIONS)):
                with self.assertRaises(RuntimeError) as caught:
                    call()
                self.assertEqual(str(caught.exception), "TYPESAFE_API_KEY is not set")
            owned.assert_not_called()
        with patch.dict(os.environ, {**env, "TYPESAFE_API_KEY": ""}, clear=True), \
                self.assertRaises(RuntimeError):
            makeJevDecision("x", "Which?", ["a", "b"])

    def test_timeout_reaches_owned_client(self):
        with patch.dict(os.environ, {"TYPESAFE_API_KEY": "offline-test"}), \
                patch("typesafe_sdk.TypeSafeClient") as owned:
            owned.return_value.__enter__.return_value = self.client
            makeJevDecisions("x", self.QUESTIONS, timeout=90)
            owned.assert_called_once_with(timeout=90)

    def test_cli_routes_questions_to_batch(self):
        request = {"context": "x", "questions": self.QUESTIONS}
        original = makeJevDecisions

        def inject(**kwargs):
            return original(**kwargs, client=self.client)

        output = io.StringIO()
        with patch.object(jev_decision, "makeJevDecisions", side_effect=inject), \
                patch("sys.argv", ["jev_decision.py"]), \
                patch("sys.stdin", io.StringIO(json.dumps(request))), redirect_stdout(output):
            self.assertEqual(jev_decision.main(), 0)
        self.assertEqual(json.loads(output.getvalue())["answers"], self.answers)
        errors = io.StringIO()
        with patch.object(jev_decision, "makeJevDecisions", side_effect=RuntimeError("PRIVATE BODY")), \
                patch("sys.argv", ["jev_decision.py"]), \
                patch("sys.stdin", io.StringIO(json.dumps(request))), redirect_stderr(errors):
            self.assertEqual(jev_decision.main(), 1)
        self.assertEqual(json.loads(errors.getvalue()), {"status": "error", "error_type": "RuntimeError"})


if __name__ == "__main__":
    unittest.main()
