#!/usr/bin/env python3
"""Generate a deterministic commit-message draft from a local Git diff.

Provides both a CLI interface and a minimal OpenAI‑compatible REST API using FastAPI.
"""

import argparse
import sys
from datetime import datetime
import uuid
from typing import List, Optional, Dict, Any

from gittxt.core import collect_changes, generate_draft
from gittxt.logger import log_error
from gittxt.autonomous import generate_autonomous

# ---------------------------------------------------------------------------
# CLI implementation (unchanged except for additional imports above)
# ---------------------------------------------------------------------------

def main():
    # Handle shortcut 'westie start' before argparse consumes it
    if len(sys.argv) > 1 and sys.argv[1] == "start":
        # Remove the 'start' token so argparse doesn't see it as an unknown argument
        sys.argv.pop(1)
        serve_requested = True
    else:
        serve_requested = False
    parser = argparse.ArgumentParser(
        description="Draft a commit message from changes in the current Git repository."
    )
    parser.add_argument(
        "command",
        nargs='?',
        default=None,
        help="Optional command, e.g., 'start' to launch the API server",
    )
    parser.add_argument(
        "--staged",
        action="store_true",
        help="Analyze only staged changes (default: all tracked changes vs HEAD).",
    )
    parser.add_argument(
        "--stat-only",
        action="store_true",
        help="Print only the change summary, not a commit-message draft.",
    )
    parser.add_argument(
        "--analyze",
        action="store_true",
        help="Analyze diff for functions, conditions, validations, imports, and config changes.",
    )
    parser.add_argument(
        "--autonomous",
        action="store_true",
        help="Use autonomous AST‑based fact extraction and compositional generation (no templates).",
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help="Start the FastAPI server locally (equivalent to 'westie start')",
    )
    args = parser.parse_args()
    # If the shortcut was used, force serve mode
    if serve_requested:
        args.serve = True

    # Treat the positional "start" command as a request to serve the API
    if args.command == "start":
        args.serve = True
    # If the serve flag is active, run the server and exit early
    if args.serve:
        import uvicorn
        # Use a high, unlikely‑to‑conflict port (default 54321)
        uvicorn.run(app, host="0.0.0.0", port=54321)
        return 0

    try:
        data = collect_changes(staged=args.staged)
        if not data["changed_files"] and not data["untracked"]:
            print("No changes found.")
            return 0

        if args.autonomous:
            result = generate_autonomous(data["diff"], staged=args.staged, untracked=data["untracked"])
            print(result["text"])
            if result["confidence"] < 1.0:
                print(f"[confidence: {result['confidence']:.2f} · {result.get('band', 'unlabeled')}]"
                )
            return 0

        draft = generate_draft(data, analyze=args.analyze)

        if args.stat_only:
            print(draft["summary"])
            return 0

        print(draft["subject"])
        print()
        print(draft["summary"])
        print()
        print("Files:")
        for path in draft["files"]:
            marker = " (untracked)" if path in draft["untracked"] else ""
            print(f"- {path}{marker}")

        if args.analyze and "analysis" in draft:
            print()
            print("Analysis:")
            for category in ["functions", "conditions", "validations", "imports", "config"]:
                items = draft["analysis"][category]
                if items:
                    print(f"  {category.capitalize()}:")
                    for item in items[:10]:
                        print(f"    - {item}")
                    if len(items) > 10:
                        print(f"    ... and {len(items) - 10} more")
        return 0
    except Exception as exc:
        log_error("main", exc)
        print(f"error: {exc}", file=sys.stderr)
        return 2

# ---------------------------------------------------------------------------
# FastAPI server (OpenAI‑compatible minimal implementation)
# ---------------------------------------------------------------------------

try:
    from fastapi import FastAPI, HTTPException
    from pydantic import BaseModel
except ImportError:  # FastAPI not installed – the API will be unavailable
    FastAPI = None  # type: ignore

if FastAPI is not None:
    app = FastAPI(title="Westie OpenAI‑compatible API")

    class Message(BaseModel):
        role: str
        content: str

    class ChatCompletionRequest(BaseModel):
        model: str
        messages: List[Message]
        stream: Optional[bool] = False

    class ChatCompletionChoice(BaseModel):
        index: int
        message: Message
        finish_reason: str = "stop"

    class ChatCompletionResponse(BaseModel):
        id: str
        object: str = "chat.completion"
        created: int
        model: str
        choices: List[ChatCompletionChoice]

    @app.get("/")
    def root():
        return {"message": "Westie API – use /v1/models or /v1/chat/completions"}

    @app.get("/v1/models")
    def list_models():
        return {
            "object": "list",
            "data": [
                {
                    "id": "westie-1",
                    "object": "model",
                    "created": int(datetime.now().timestamp()),
                    "owned_by": "westie",
                }
            ],
        }

    @app.post("/v1/chat/completions")
    def chat_completions(req: ChatCompletionRequest):
        """Return a commit‑message draft.
        If the deployment environment does not contain a .git repository
        (which is the case on Vercel), we fall back to a static example
        message instead of raising a 400 error.
        """
        # Basic validation – only the static model is supported
        if req.model != "westie-1":
            raise HTTPException(status_code=400, detail="Unsupported model")
        try:
            # Attempt to gather repo diff and generate a draft
            data = collect_changes(staged=False)
            draft = generate_draft(data, analyze=False)
            content = f"{draft['subject']}\n\n{draft['summary']}"
        except Exception as exc:
            try:
                # Try to generate a draft using the autonomous mode (no diff needed)
                draft = generate_autonomous("", staged=False, untracked=False)
                content = f"{draft['subject']}\n\n{draft['summary']}"
            except Exception:
                # If autonomous also fails, fall back to a static example
                content = (
                    "Could not access a Git repository in this environment. "
                    "This is a static example message generated for demonstration purposes."
                )
        response = ChatCompletionResponse(
            id=f"chatcml-{uuid.uuid4().hex}",
            created=int(datetime.now().timestamp()),
            model=req.model,
            choices=[
                ChatCompletionChoice(
                    index=0,
                    message=Message(role="assistant", content=content),
                )
            ],
        )
        return response

if __name__ == "__main__":
    # When executed directly, run the CLI (preserving original behaviour)
    if len(sys.argv) > 1 and sys.argv[1] == "start":
        # Simple shortcut: `westie start` launches the API locally
        try:
            import uvicorn
        except ImportError as e:
            raise SystemExit("uvicorn is required to run the server. Install with 'pip install uvicorn'.") from e
        # Run the FastAPI app on localhost using the same high, unlikely port
        uvicorn.run(app, host="0.0.0.0", port=54321)
    else:
        sys.exit(main())
