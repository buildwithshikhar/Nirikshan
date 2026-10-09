"""Structured (JSON) logging with secrets redacted.

Logged: request method, path (never the query string), status, duration, authenticated principal.
Never logged: request bodies, Authorization headers, passwords, session tokens. A redaction filter
also masks anything shaped like a session token or a password field if one is ever formatted in.
"""

import json
import logging
import os
import re
import sys
from datetime import datetime, timezone

_TOKEN = re.compile(r"nrk_[A-Za-z0-9_\-]{8,}")
_PASSWORD = re.compile(
    r"(?i)(password|passphrase|secret|authorization)(\"?\s*[:=]\s*\"?)[^\s\",}]+"
)


def redact(text: str) -> str:
    return _PASSWORD.sub(r"\1\2[redacted]", _TOKEN.sub("nrk_[redacted]", text))


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = ()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        out.update(getattr(record, "fields", {}))
        if record.exc_info:
            out["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(out, default=str)


def setup() -> None:
    log = logging.getLogger("nirikshan")
    if log.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(RedactFilter())
    if os.getenv("NIRIKSHAN_LOG_FORMAT", "json") == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    log.addHandler(handler)
    log.setLevel(os.getenv("NIRIKSHAN_LOG_LEVEL", "INFO").upper())
    log.propagate = False


access = logging.getLogger("nirikshan.access")
