"""Validated Jev request construction and bounded decisions through the TypeSafe SDK."""

import argparse
import hashlib
import json
import math
import os
import re
import sys


_MAX_STATE_BYTES = 64 * 1024
_MAX_QUESTIONS_BYTES = 48 * 1024
_MAX_REQUEST_BYTES = 64 * 1024


def _canonical_json(value):
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256_json(value):
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _json_size(value):
    return len(_canonical_json(value).encode("utf-8"))


def _nonempty_json_value(value, label):
    if isinstance(value, str):
        if not value.strip():
            raise ValueError(f"{label} must not be empty")
        return
    if isinstance(value, (dict, list)):
        if not value:
            raise ValueError(f"{label} must not be empty")
        return
    if value is None:
        raise ValueError(f"{label} must not be null")


def _build_spec(kind, question, acceptable_answers):
    """Validate one question's inputs and return its SDK question spec."""
    if not isinstance(question, (str, dict, list)):
        raise ValueError("question instructions must be JSON text, an object, or an array")
    _nonempty_json_value(question, "question instructions")
    spec = {"type": kind, "instructions": question}

    if kind == "choice":
        if isinstance(acceptable_answers, list):
            if any(not isinstance(v, str) or not v.strip() for v in acceptable_answers):
                raise ValueError("choice IDs must be nonempty strings")
            if len(set(acceptable_answers)) != len(acceptable_answers):
                raise ValueError("choice IDs must be unique")
            acceptable_answers = dict.fromkeys(acceptable_answers)
        if not isinstance(acceptable_answers, dict) or not 2 <= len(acceptable_answers) <= 255:
            raise ValueError("choice requires 2–255 acceptable answers")
        if any(not isinstance(k, str) or not k.strip() for k in acceptable_answers):
            raise ValueError("choice IDs must be nonempty strings")
        if any(v is not None and not isinstance(v, (str, dict, list))
               for v in acceptable_answers.values()):
            raise ValueError("choice descriptions must be JSON text, objects, arrays, or null")
        spec["criteria"] = acceptable_answers

    elif kind == "score":
        if not isinstance(acceptable_answers, list) or not 2 <= len(acceptable_answers) <= 10:
            raise ValueError("score requires 2–10 ordered descriptions")
        if any(not isinstance(v, (str, dict, list)) or not v for v in acceptable_answers):
            raise ValueError("score levels require descriptions")
        spec["criteria"] = acceptable_answers

    elif kind == "noul":
        if acceptable_answers is not None:
            if (
                not isinstance(acceptable_answers, dict)
                or set(acceptable_answers) != {"true", "false"}
                or any(
                    v is not None and not isinstance(v, (str, dict, list))
                    for v in acceptable_answers.values()
                )
            ):
                raise ValueError(
                    "noul criteria, when supplied, must contain exactly true and false descriptions"
                )
            spec["criteria"] = acceptable_answers

    else:
        raise ValueError("use choice, score, or noul")

    _canonical_json(spec)
    return spec


def _normalize_questions(questions):
    if not isinstance(questions, dict) or not questions:
        raise ValueError("questions must be a nonempty object")
    specs = {}
    for name, item in questions.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError("question IDs must be nonempty strings")
        if not isinstance(item, dict):
            raise ValueError("each question must be an object")
        specs[name] = _build_spec(
            item.get("type"),
            item.get("instructions"),
            item.get("criteria"),
        )
    return specs


def buildJevRequest(
    context,
    questions,
    *,
    model=None,
    purpose=None,
    previous_decision_sha256=None,
    change_reason=None,
):
    """Build and validate one deterministic System One request.

    The returned request field is SDK-shaped: state, questions, and model. The
    builder also returns canonical hashes and byte counts for audit/revision
    history. previous_decision_sha256 is the prior revision's hash of only
    state+questions; when supplied, an unchanged semantic request is rejected.

    These byte ceilings are conservative local safety limits for this skill,
    not vendor API limits. They force deliberate evidence projection rather
    than silent truncation.
    """
    if not isinstance(context, (str, dict, list)):
        raise ValueError("context must be JSON text, an object, or an array")
    _nonempty_json_value(context, "context")
    specs = _normalize_questions(questions)

    if model is not None and (not isinstance(model, str) or not model.strip()):
        raise ValueError("model must be a nonempty string or null")
    if purpose is not None and (not isinstance(purpose, str) or not purpose.strip()):
        raise ValueError("purpose must be a nonempty string or null")

    if previous_decision_sha256 is not None:
        if (
            not isinstance(previous_decision_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", previous_decision_sha256) is None
        ):
            raise ValueError("previous_decision_sha256 must be a lowercase SHA-256")
        if not isinstance(change_reason, str) or not change_reason.strip():
            raise ValueError("a rebuilt request requires a nonempty change_reason")
    elif change_reason is not None:
        raise ValueError("change_reason requires previous_decision_sha256")

    _canonical_json(context)
    _canonical_json(specs)

    state_bytes = _json_size(context)
    questions_bytes = _json_size(specs)
    if state_bytes > _MAX_STATE_BYTES:
        raise ValueError("project state to at most 64 KiB")
    if questions_bytes > _MAX_QUESTIONS_BYTES:
        raise ValueError("project questions to at most 48 KiB")

    provider_request = {
        "state": context,
        "questions": specs,
        "model": model,
    }
    request_bytes = _json_size(provider_request)
    if request_bytes > _MAX_REQUEST_BYTES:
        raise ValueError("project the complete Jev request to at most 64 KiB")

    decision_payload = {"state": context, "questions": specs}
    decision_sha256 = _sha256_json(decision_payload)
    if previous_decision_sha256 == decision_sha256:
        raise ValueError(
            "rebuilt Jev request is semantically unchanged; gather new evidence "
            "or change the alternatives before calling Jev again"
        )

    return {
        "request": provider_request,
        "purpose": purpose,
        "request_sha256": _sha256_json(provider_request),
        "decision_sha256": decision_sha256,
        "state_sha256": _sha256_json(context),
        "questions_sha256": _sha256_json(specs),
        "sizes": {
            "state_bytes": state_bytes,
            "questions_bytes": questions_bytes,
            "request_bytes": request_bytes,
        },
        "revision": {
            "previous_decision_sha256": previous_decision_sha256,
            "change_reason": change_reason,
        },
    }


def rebuildJevRequest(previous, context, questions, *, model=None, purpose=None, change_reason):
    """Build a changed revision and reject unchanged state+questions."""
    if not isinstance(previous, dict):
        raise ValueError("previous request record must be an object")
    previous_hash = previous.get("decision_sha256")
    return buildJevRequest(
        context,
        questions,
        model=model,
        purpose=purpose,
        previous_decision_sha256=previous_hash,
        change_reason=change_reason,
    )


def _validate_answer(kind, criteria, answer):
    """Raise ValueError unless answer matches the primitive and its allowed rubric."""
    if not isinstance(answer, dict):
        raise ValueError("Jev returned missing or malformed answer data")
    if answer.get("type") != kind:
        raise ValueError("Jev returned the wrong answer type")

    def number(value, low, high):
        return (isinstance(value, (int, float)) and not isinstance(value, bool)
                and math.isfinite(value) and low <= value <= high)

    if kind == "noul":
        if not number(answer.get("noul"), 0, 1):
            raise ValueError("Jev returned an invalid Noul probability")
        return

    allowed = set(criteria) if kind == "choice" else {str(i) for i in range(len(criteria))}
    probabilities = answer.get("probabilities")
    if (not isinstance(probabilities, dict) or set(probabilities) != allowed
            or not all(number(v, 0, 1) for v in probabilities.values())
            or not math.isclose(sum(probabilities.values()), 1,
                                abs_tol=0.005 * len(allowed) + 1e-9)
            or not number(answer.get("confidence"), 0, 1)):
        raise ValueError("Jev returned an invalid answer distribution")
    if kind == "choice" and answer.get("choice") not in allowed:
        raise ValueError("Jev returned a choice outside the acceptable answer set")
    if kind == "score" and not number(answer.get("score"), 0, len(allowed) - 1):
        raise ValueError("Jev returned a score outside the rubric")


def _send_built_request(built, client, timeout):
    request = built["request"]
    if client is None:
        if not os.environ.get("TYPESAFE_API_KEY"):
            raise RuntimeError("TYPESAFE_API_KEY is not set")
        from typesafe_sdk import TypeSafeClient
        with TypeSafeClient(timeout=timeout) as owned_client:
            return _send_built_request(built, owned_client, timeout)

    response = client.system_one(
        state=request["state"],
        questions=request["questions"],
        model=request["model"],
    )
    result = response.raw_http_response.json()
    answers = result.get("answers") if isinstance(result, dict) else None
    if not isinstance(answers, dict):
        raise ValueError("Jev returned missing or malformed answer data")
    for name, spec in request["questions"].items():
        _validate_answer(spec["type"], spec.get("criteria"), answers.get(name))
    return result


def _decide(context, specs, model, client, timeout):
    """Compatibility path: build, send one system_one call, validate every answer."""
    built = buildJevRequest(context, specs, model=model)
    return _send_built_request(built, client, timeout)


def makeJevDecision(context, question, acceptable_answers=None, *, kind="choice",
                    model=None, client=None, timeout=30):
    """Return the API result set; raise on invalid input, failure, or invalid evidence.

    Choice accepts {id: description} or a list of unique IDs. Score accepts an
    ordered list of 2–10 descriptions. Noul optionally accepts
    {"true": ..., "false": ...} criteria clarifying the proposition.
    """
    spec = _build_spec(kind, question, acceptable_answers)
    return _decide(context, {"decision": spec}, model, client, timeout)


def makeJevDecisions(context, questions, *, model=None, client=None, timeout=30):
    """Ask several independent questions over one context in a single call."""
    specs = _normalize_questions(questions)
    return _decide(context, specs, model, client, timeout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request", nargs="?", default="-", help="JSON file, or - for stdin")
    parser.add_argument(
        "--build-only",
        action="store_true",
        help="validate and print normalized request metadata without calling Jev",
    )
    args = parser.parse_args()
    try:
        if args.request == "-":
            request = json.load(sys.stdin)
        else:
            with open(args.request, encoding="utf-8") as stream:
                request = json.load(stream)

        if args.build_only:
            if "questions" in request:
                built = buildJevRequest(
                    request.get("context"),
                    request["questions"],
                    model=request.get("model"),
                    purpose=request.get("purpose"),
                    previous_decision_sha256=request.get("previous_decision_sha256"),
                    change_reason=request.get("change_reason"),
                )
            else:
                spec = _build_spec(
                    request.get("kind", "choice"),
                    request.get("question"),
                    request.get("acceptable_answers"),
                )
                built = buildJevRequest(
                    request.get("context"),
                    {"decision": spec},
                    model=request.get("model"),
                    purpose=request.get("purpose"),
                    previous_decision_sha256=request.get("previous_decision_sha256"),
                    change_reason=request.get("change_reason"),
                )
            print(json.dumps(built, allow_nan=False))
        else:
            result = (makeJevDecisions if "questions" in request else makeJevDecision)(**request)
            print(json.dumps(result, allow_nan=False))
    except Exception as exc:
        print(json.dumps({"status": "error", "error_type": type(exc).__name__}), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
