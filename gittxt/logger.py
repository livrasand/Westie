"""Logging utilities."""
import sys
from datetime import datetime


def log_error(func_name, error):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] ERROR in {func_name}: {error}", file=sys.stderr)


def log_info(msg):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] INFO: {msg}", file=sys.stderr)
