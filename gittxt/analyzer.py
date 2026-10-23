"""Diff analyzer."""
import re


def analyze_diff(diff_text):
    """Analyze diff to detect function, condition, validation, import, and config changes."""
    changes = {
        "functions": [],
        "conditions": [],
        "validations": [],
        "imports": [],
        "config": [],
    }

    current_file = None

    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            match = re.match(r"diff --git a/(.*?) b/(.*)$", line)
            if match:
                current_file = match.group(2)
            continue
        elif line.startswith("+") and not line.startswith("+++"):
            content = line[1:]
            if not current_file:
                continue

            # Detect imports
            if re.match(r'^\s*(import\s+|from\s+.+\s+import\s+)', content):
                changes["imports"].append(f"{current_file}: {content.strip()}")
                continue

            # Detect function definitions
            if re.match(r'^\s*(def\s+\w+|class\s+\w+|function\s+\w+|async\s+def\s+\w+)', content):
                changes["functions"].append(f"{current_file}: {content.strip()}")
                continue

            # Detect config
            if current_file.endswith(('.json', '.yaml', '.yml', '.toml', '.ini', '.conf', '.env', '.config')):
                if '=' in content or ':' in content or re.match(r'^\s*[\[\{"]', content):
                    changes["config"].append(f"{current_file}: {content.strip()}")
                    continue

            # Detect conditions
            if re.search(r'\b(if\s+|elif\s+|else\s*:|while\s+|for\s+|switch\s+|case\s+)', content):
                changes["conditions"].append(f"{current_file}: {content.strip()}")
                continue

            # Detect validations
            if re.search(r'\b(validate|check|assert|ensure|verify|raise\s+|throw\s+|return\s+(False|None)|\.get\(|isinstance|len\(|re\.match|re\.search)', content, re.I):
                changes["validations"].append(f"{current_file}: {content.strip()}")
                continue

    return changes
