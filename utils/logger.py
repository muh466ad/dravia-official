"""Dravia State Bot - Centralized Logging

Rotating file handlers per domain:
  bot.log, transactions.log, police.log, audit.log, errors.log, admin.log
"""
import logging
import os
from logging.handlers import RotatingFileHandler

LOG_DIR = os.getenv("LOG_DIR", "logs")
os.makedirs(LOG_DIR, exist_ok=True)

# domain log file -> level
_LOG_FILES = {
    "bot": "bot.log",
    "transactions": "transactions.log",
    "police": "police.log",
    "audit": "audit.log",
    "errors": "errors.log",
    "admin": "admin.log",
}

_FORMAT = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

_configured = False


def _configure() -> None:
    global _configured
    if _configured:
        return
    root = logging.getLogger("Dravia")
    root.setLevel(logging.INFO)
    for name, filename in _LOG_FILES.items():
        handler = RotatingFileHandler(
            os.path.join(LOG_DIR, filename),
            maxBytes=2_000_000,
            backupCount=5,
            encoding="utf-8",
        )
        handler.setFormatter(_FORMAT)
        if name == "errors":
            handler.setLevel(logging.WARNING)
        else:
            handler.setLevel(logging.INFO)
        sub = logging.getLogger(f"Dravia.{name}")
        sub.addHandler(handler)
        sub.propagate = False
    _configured = True


def get_logger(domain: str = "bot") -> logging.Logger:
    """Return a logger writing to the domain's rotating log file."""
    _configure()
    if domain not in _LOG_FILES:
        domain = "bot"
    return logging.getLogger(f"Dravia.{domain}")


# Convenience loggers
bot_log = get_logger("bot")
tx_log = get_logger("transactions")
police_log = get_logger("police")
audit_log = get_logger("audit")
error_log = get_logger("errors")
admin_log = get_logger("admin")


def log_error(context: str, exc: Exception) -> None:
    """Log an exception to errors.log with context."""
    error_log.error("%s: %s", context, exc, exc_info=True)
