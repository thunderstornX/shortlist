"""Structured JSONL logging.

One JSON object per line so a run can be replayed and audited afterwards.
Candidate CV text is never written unless config explicitly allows it, and
listed PII fields are redacted regardless.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_PHONE = re.compile(r"\+?\d[\d\s().-]{7,}\d")


def redact(text: str) -> str:
    text = _EMAIL.sub("<email>", text)
    return _PHONE.sub("<phone>", text)


class RunLog:
    def __init__(self, run_id: str, directory: Path, log_cv_text: bool = False) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / f"{run_id}.jsonl"
        self.run_id = run_id
        self.log_cv_text = log_cv_text
        self._t0 = time.time()

    def event(self, kind: str, **fields: Any) -> None:
        payload: dict[str, Any] = {
            "ts": round(time.time(), 3),
            "elapsed": round(time.time() - self._t0, 3),
            "run_id": self.run_id,
            "event": kind,
        }
        for k, v in fields.items():
            if k in {"cv_text", "prompt"} and not self.log_cv_text:
                payload[k + "_chars"] = len(v) if isinstance(v, str) else None
                continue
            payload[k] = redact(v) if isinstance(v, str) else v
        with self.path.open("a") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
