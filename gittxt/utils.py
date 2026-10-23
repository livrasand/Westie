"""General utilities."""
import re
from pathlib import Path


def humanize(path):
    name = Path(path).stem
    name = re.sub(r"[-_]+", " ", name)
    name = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name)
    return name.strip() or Path(path).name
