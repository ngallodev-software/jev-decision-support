"""One bounded agent decision through the official TypeSafe SDK."""

import argparse
import json
import math
import sys


def makeJevDecision(context, question, acceptable_answers=None, *, kind="choice",
                    model=None, client=None):
    """Return the API result set; raise on invalid input, failure, or invalid evidence.

    Choice accepts {id: description} or a list of unique IDs. Score accepts an
    ordered list of 2–10 descriptions. Noul needs no acceptable_answers.
    An injected SDK client remains owned by the caller.
    """
    if not isinstance(question, str) or not question.strip():
        raise ValueError("question must be a nonempty string")
    if not isinstance(context, (str, dict, list)):
        raise ValueError("context must be JSON text, an object, or an array")
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
    elif kind != "noul" or acceptable_answers is not None:
        raise ValueError("use choice, score, or noul; noul takes no acceptable_answers")
    # Local payload ceiling, not a vendor limit. Project evidence rather than truncate it.
    payload = json.dumps({"state": context, "questions": {"decision": spec}}, allow_nan=False)
    if len(payload.encode("utf-8")) > 65536:
        raise ValueError("project context and question to at most 64 KiB")

    if client is None:
        from typesafe_sdk import TypeSafeClient
        with TypeSafeClient(timeout=30) as owned_client:
            return makeJevDecision(context, question, acceptable_answers,
                                   kind=kind, model=model, client=owned_client)
    response = client.system_one(state=context, questions={"decision": spec}, model=model)
    result = response.raw_http_response.json()
    answer = result["answers"]["decision"]
    if answer.get("type") != kind:
        raise ValueError("Jev returned the wrong answer type")

    def number(value, low, high):
        return (isinstance(value, (int, float)) and not isinstance(value, bool)
                and math.isfinite(value) and low <= value <= high)

    if kind == "noul":
        if not number(answer.get("noul"), 0, 1):
            raise ValueError("Jev returned an invalid Noul probability")
    else:
        allowed = set(acceptable_answers) if kind == "choice" else {
            str(i) for i in range(len(acceptable_answers))}
        probabilities = answer.get("probabilities")
        if (not isinstance(probabilities, dict) or set(probabilities) != allowed
                or not all(number(v, 0, 1) for v in probabilities.values())
                or not math.isclose(sum(probabilities.values()), 1, abs_tol=1e-5)
                or not number(answer.get("confidence"), 0, 1)):
            raise ValueError("Jev returned an invalid answer distribution")
        if kind == "choice" and answer.get("choice") not in allowed:
            raise ValueError("Jev returned a choice outside the acceptable answer set")
        if kind == "score" and not number(answer.get("score"), 0, len(allowed) - 1):
            raise ValueError("Jev returned a score outside the rubric")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request", nargs="?", default="-", help="JSON file, or - for stdin")
    args = parser.parse_args()
    try:
        if args.request == "-":
            request = json.load(sys.stdin)
        else:
            with open(args.request, encoding="utf-8") as stream:
                request = json.load(stream)
        result = makeJevDecision(**request)
        print(json.dumps(result, allow_nan=False))
    except Exception as exc:
        # SDK errors can contain request bodies. Report the class, never those bodies.
        print(json.dumps({"status": "error", "error_type": type(exc).__name__}), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
