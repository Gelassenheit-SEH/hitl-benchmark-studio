"""Local web server and state transitions for the public HITL Studio demo."""
import argparse
import copy
import json
import secrets
import threading
from collections import OrderedDict
from itertools import zip_longest
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from demo_cases import SAMPLES, inject, revision_reply
from workflow import (
    ApiError, CONTROLLED_ERROR_CATEGORIES, ERROR_FIELDS, REVIEWABLE_FIELDS,
    allocate_controlled_error_counts, append_annotation_version, now_iso,
    validate_controlled_error_draft, validate_field_reviews, validate_revision_draft,
)

PRESETS = {
    "balanced": {
        "label": "Balanced", "ratios": {"C1": 25, "C2": 25, "C3": 25, "C4": 25},
    },
    "quantitative": {
        "label": "Quantitative focus", "ratios": {"C1": 25, "C2": 0, "C3": 25, "C4": 50},
    },
}
RELEASE_REMINDERS = (
    "Compare the candidate with the source evidence.",
    "Check that it contains one intentional error in the assigned category.",
    "Check that the annotation identifies the error and proposes a valid repair.",
)
JUDGMENTS = ("clear_violation", "no_violation", "insufficient_evidence")
ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
REPLAY_FILE = ROOT / "replays" / "recorded-replays.json"
REPLAY_IMAGE = "replay-scale-bar.png"


def text_field(value, *, required=True):
    if not isinstance(value, str) or len(value) > 1000 or (required and not value.strip()):
        raise ApiError(400, "Provide a short text value (up to 1,000 characters).")
    return value.strip()


def preview(preset):
    if not isinstance(preset, str) or preset not in PRESETS:
        raise ApiError(400, "Select a supported batch preset.")
    config = PRESETS[preset]
    counts = allocate_controlled_error_counts(len(SAMPLES), config["ratios"])
    # Interleave categories. Both presets start with the guided quantitative example.
    runs = ([code] * counts[code] for code in ("C4", "C1", "C2", "C3"))
    codes = [code for group in zip_longest(*runs) for code in group if code is not None]
    return {
        "preset": preset, "planned": counts, "ratios": config["ratios"],
        "assignments": [
            {"id": sample["id"], "title": sample["title"], "subject": sample["subject"], "category": code}
            for sample, code in zip(SAMPLES, codes)
        ],
    }


def apply_injection(sample, round_id=None):
    candidate, annotation = validate_controlled_error_draft(
        inject(sample["id"], sample["category"], reinjection=round_id is not None),
        CONTROLLED_ERROR_CATEGORIES[sample["category"]],
    )
    annotation["actor"] = "simulated_model"
    version = append_annotation_version(
        sample, annotation, "reinjection" if round_id else "initial", round_id,
    )
    sample["candidates"].append({
        "version": len(sample["candidates"]) + 1,
        "annotation_version": version,
        "category": sample["category"],
        "text": candidate,
        "created_at": now_iso(),
    })


class Studio:
    def __init__(self):
        self.batch = None

    def snapshot(self):
        if self.batch is None:
            return {"batch": None}
        batch = copy.deepcopy(self.batch)
        batch["generated"] = dict.fromkeys(CONTROLLED_ERROR_CATEGORIES, 0)
        batch["released"] = dict.fromkeys(CONTROLLED_ERROR_CATEGORIES, 0)
        for sample in batch["samples"]:
            batch["generated"][sample["category"]] += bool(sample["candidates"])
            batch["released"][sample["category"]] += sample["status"] == "released"
        return {"batch": batch}

    def start(self, preset):
        plan = preview(preset)
        records = []
        for source, assignment in zip(SAMPLES, plan["assignments"]):
            sample = {
                **copy.deepcopy(source), "category": assignment["category"],
                "status": "needs_review", "candidates": [], "review_history": [],
            }
            apply_injection(sample)
            records.append(sample)
        self.batch = {
            "id": secrets.token_hex(8), "preset": preset,
            "planned": plan["planned"], "samples": records,
        }
        return self.snapshot()["batch"]

    def reset(self):
        self.batch = None

    def review(self, payload):
        if self.batch is None or payload.get("batch_id") != self.batch["id"]:
            raise ApiError(409, "This batch changed. Reload the current session.")
        index = next((i for i, row in enumerate(self.batch["samples"])
                      if row["id"] == payload.get("sample_id")), None)
        if index is None:
            raise ApiError(404, "Sample not found.")

        sample = copy.deepcopy(self.batch["samples"][index])
        version = sample["ai_preannotation_versions"][-1]["version"]
        if type(payload.get("version")) is not int or payload["version"] != version:
            raise ApiError(409, "This annotation changed. Reload before applying another action.")
        if sample["status"] != "needs_review":
            raise ApiError(409, "This sample already has a final decision.")

        action = payload.get("action")
        round_id = f"R{len(sample['review_history']) + 1}"
        annotation = sample["ai_preannotation"]
        event = {
            "id": round_id, "action": action, "actor": "human", "time": now_iso(),
            "from_candidate_version": sample["candidates"][-1]["version"],
            "from_annotation_version": version,
        }
        if action == "reinject":
            if len(sample["candidates"]) > 1:
                raise ApiError(400, "This demo includes one replacement candidate per sample.")
            event["note"] = text_field(payload.get("note"))
            apply_injection(sample, round_id)
        elif action == "revise":
            instructions = payload.get("instructions")
            if not isinstance(instructions, dict) or not set(instructions) <= set(REVIEWABLE_FIELDS):
                raise ApiError(400, "Choose one or more supported fields.")
            if annotation["suggested_judgment"] != "clear_violation":
                raise ApiError(400, "Field revision requires an error annotation.")
            instructions = {
                key: value for key, raw in instructions.items()
                if (value := text_field(raw, required=False))
            }
            field_reviews = validate_field_reviews({
                field: {
                    "decision": "needs_revision" if field in instructions else "agree",
                    "revision_instruction": instructions.get(field, ""),
                }
                for field in REVIEWABLE_FIELDS
            })
            draft = validate_revision_draft(revision_reply(sample))
            revised = copy.deepcopy(annotation)
            for field in REVIEWABLE_FIELDS:
                if field_reviews[field]["decision"] == "needs_revision":
                    revised["suggested_errors"][0][field] = draft[field]
            revised["actor"] = "simulated_model"
            event["instructions"] = instructions
            event["changed_fields"] = [
                field for field in REVIEWABLE_FIELDS
                if revised["suggested_errors"][0][field] != annotation["suggested_errors"][0][field]
            ]
            append_annotation_version(sample, revised, "selective_revision", round_id)
        elif action == "override":
            judgment = payload.get("judgment", "")
            if judgment == "":
                judgment = annotation["suggested_judgment"]
            if judgment not in JUDGMENTS:
                raise ApiError(400, "Select a judgment.")
            event["judgment"] = judgment
            revised = {"suggested_judgment": judgment, "suggested_errors": [],
                       "uncertainties": [], "actor": "human"}
            if judgment == "clear_violation":
                supplied = payload.get("fields", {})
                if not isinstance(supplied, dict) or not set(supplied) <= set(ERROR_FIELDS):
                    raise ApiError(400, "Unsupported annotation fields.")
                previous = next((version["annotation"]["suggested_errors"][0]
                                 for version in reversed(sample["ai_preannotation_versions"])
                                 if version["annotation"]["suggested_errors"]), {})
                changes = {
                    key: value for key, raw in supplied.items()
                    if (value := text_field(raw, required=False))
                }
                updated = {**previous, **changes}
                if set(updated) != set(ERROR_FIELDS) or updated["error_category"] not in CONTROLLED_ERROR_CATEGORIES.values():
                    raise ApiError(400, "A complete error annotation with a valid category is required.")
                revised["suggested_errors"] = [updated]
            if (judgment == annotation["suggested_judgment"]
                    and revised["suggested_errors"] == annotation["suggested_errors"]):
                raise ApiError(400, "Change the judgment or at least one field.")
            append_annotation_version(sample, revised, "human_override", round_id)
        elif action == "release":
            errors = annotation["suggested_errors"]
            if not errors or errors[0]["error_category"] != CONTROLLED_ERROR_CATEGORIES[sample["category"]]:
                raise ApiError(400, "A released negative example needs an annotation in the assigned category.")
            sample["status"] = "released"
        elif action == "reject":
            event["note"] = text_field(payload.get("note"))
            sample["status"] = "rejected"
        else:
            raise ApiError(400, "Unsupported review action.")

        event["candidate_version"] = sample["candidates"][-1]["version"]
        event["annotation_version"] = sample["ai_preannotation_versions"][-1]["version"]
        sample["review_history"].append(event)
        self.batch["samples"][index] = sample
        return self.snapshot()["batch"]

    def export(self):
        records = []
        for sample in self.batch["samples"] if self.batch else []:
            if sample["status"] != "released":
                continue
            last = sample["review_history"][-1]
            records.append({
                "schema_version": 2, "mode": "simulated_model", "batch_id": self.batch["id"],
                "id": sample["id"], "question": sample["question"], "category": sample["category"],
                "category_name": CONTROLLED_ERROR_CATEGORIES[sample["category"]],
                "candidate_version": last["candidate_version"], "annotation_version": last["annotation_version"],
                "candidate": sample["candidates"][-1]["text"], "annotation": sample["ai_preannotation"],
                "release": {
                    "actor": "human", "decision": "reviewed", "time": last["time"],
                },
                "reference_evidence": sample["evidence"],
                "candidate_history": sample["candidates"],
                "annotation_history": sample["ai_preannotation_versions"],
                "review_history": sample["review_history"],
            })
        return copy.deepcopy(records)


class Handler(BaseHTTPRequestHandler):
    routes = {
        "/practice": ("index.html", "text/html; charset=utf-8"),
        "/replay": ("replay.html", "text/html; charset=utf-8"),
        "/replay.js": ("replay.js", "text/javascript; charset=utf-8"),
        "/replay.css": ("replay.css", "text/css; charset=utf-8"),
        "/app.js": ("app.js", "text/javascript; charset=utf-8"),
        "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    }

    def send_bytes(self, status, data, content_type, **headers):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        for name, value in headers.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, value, status=200, **headers):
        self.send_bytes(status, json.dumps(value, ensure_ascii=False).encode("utf-8"),
                        "application/json; charset=utf-8", **headers)

    def session(self):
        cookie = SimpleCookie()
        cookie.load(self.headers.get("Cookie", ""))
        token = cookie["studio_session"].value if "studio_session" in cookie else None
        sessions = self.server.sessions
        if token in sessions:
            sessions.move_to_end(token)
            return sessions[token], {}
        token = secrets.token_urlsafe(24)
        studio = sessions[token] = Studio()
        if len(sessions) > 64:
            sessions.popitem(last=False)
        return studio, {"Set-Cookie": f"studio_session={token}; Path=/; HttpOnly; SameSite=Strict"}

    def do_GET(self):
        if self.headers.get("Host") not in self.server.allowed_hosts:
            self.send_json({"error": "Use the local Studio address."}, 403)
            return
        path = self.path
        if path == "/":
            path = "/replay" if self.server.replays else "/practice"
        if path in self.routes:
            filename, content_type = self.routes[path]
            self.send_bytes(200, (STATIC / filename).read_bytes(), content_type)
            return
        if path == f"/assets/{REPLAY_IMAGE}" and self.server.replay_image:
            self.send_bytes(200, self.server.replay_image, "image/png")
            return
        if path == "/api/replays" and self.server.replays:
            self.send_json(self.server.replays)
            return
        if path not in ("/api/session", "/api/reviewed.jsonl"):
            self.send_json({"error": "Route not found."}, 404)
            return
        with self.server.session_lock:
            studio, headers = self.session()
            if self.path == "/api/session":
                value = {**studio.snapshot(), "categories": CONTROLLED_ERROR_CATEGORIES,
                         "presets": PRESETS, "release_reminders": RELEASE_REMINDERS,
                         "has_recorded_cases": bool(self.server.replays)}
            else:
                value = studio.export()
        if self.path == "/api/session":
            self.send_json(value, **headers)
        else:
            content = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in value)
            self.send_bytes(200, content.encode("utf-8"), "application/x-ndjson; charset=utf-8",
                            **headers, **{"Content-Disposition": 'attachment; filename="reviewed-examples.jsonl"'})

    def do_POST(self):
        try:
            if self.headers.get("Host") not in self.server.allowed_hosts:
                raise ApiError(403, "Use the local Studio address.")
            origin = self.headers.get("Origin")
            if origin and origin not in {f"http://{host}" for host in self.server.allowed_hosts}:
                raise ApiError(403, "Open Studio on the local server.")
            if self.headers.get_content_type() != "application/json":
                raise ApiError(415, "Use an application/json request.")
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 16_384:
                    raise ApiError(413, "Request body is too large or empty.")
                payload = json.loads(self.rfile.read(size))
            except (UnicodeDecodeError, ValueError) as exc:
                raise ApiError(400, "Invalid JSON request.") from exc
            if not isinstance(payload, dict):
                raise ApiError(400, "Send a JSON object.")
            with self.server.session_lock:
                studio, headers = self.session()
                if self.path == "/api/preview":
                    result = {"preview": preview(payload.get("preset"))}
                elif self.path == "/api/batch":
                    result = {"batch": studio.start(payload.get("preset"))}
                elif self.path == "/api/review":
                    result = {"batch": studio.review(payload)}
                elif self.path == "/api/reset":
                    studio.reset()
                    result = studio.snapshot()
                else:
                    raise ApiError(404, "Route not found.")
            self.send_json(result, **headers)
        except ApiError as exc:
            self.send_json({"error": str(exc)}, exc.status)

    def log_message(self, format, *args):
        pass


class StudioServer(ThreadingHTTPServer):
    def __init__(self, port, replay_path=REPLAY_FILE):
        if replay_path.is_file():
            data = json.loads(replay_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not isinstance(data.get("cases"), list):
                raise ValueError("Recorded replays must contain a cases array.")
            self.replays = data if data["cases"] else None
        else:
            self.replays = None
        image = replay_path.with_name(REPLAY_IMAGE)
        self.replay_image = image.read_bytes() if self.replays and image.is_file() else None
        super().__init__(("127.0.0.1", port), Handler)
        self.sessions = OrderedDict()
        self.session_lock = threading.Lock()
        self.allowed_hosts = {f"127.0.0.1:{self.server_port}", f"localhost:{self.server_port}"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    with StudioServer(args.port) as server:
        print(f"HITL Studio is ready at http://127.0.0.1:{server.server_port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
