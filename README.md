<p align="center">
  <img width="150" alt="Westie" src="https://github.com/user-attachments/assets/b64e97d7-3e30-4a3c-bd61-86506600f81f" />
</p>

<h1 align="center">Westie</h1>

A tiny, deterministic Git commit message generator.

Westie analyzes local Git changes and generates commit messages based on evidence from your code.

- **No AI.**
- **No network.**
- **No telemetry.**
- **No dependencies.**
- **No predefined message templates.**

## Why?

Writing commit messages is repetitive. Using an AI service to automate it can introduce unnecessary complexity, dependencies, and privacy concerns.

Westie explores a different approach: analyze what actually changed, understand the available evidence, and describe it without relying on a language model.

Everything happens locally.

## How it works

Westie examines a Git diff and attempts to describe the changes it can identify.

Rather than simply listing modified files or counting changed lines, the goal is to derive meaningful descriptions from the differences themselves.

Westie is designed to be:

- **Deterministic:** the same input produces the same output.
- **Local:** your code stays on your machine.
- **Evidence-based:** descriptions should reflect observable changes.
- **Minimal:** a small tool that is easy to inspect, modify, and understand.

When the available evidence is insufficient, Westie should avoid inventing details.

## Status

Westie is an experimental project in early development.

Its goal is to explore how useful commit messages can be generated through deterministic analysis rather than AI or a collection of hardcoded templates.

The quality of its output, supported languages, and analysis capabilities will evolve as the project develops.

## Usage

Use `westie` on any repo.

### Local API Server

You can now run a minimal OpenAI‑compatible API locally:

```bash
westie start        # Shortcut to launch the server
# or
westie --serve      # Equivalent flag
```

The server starts on **http://0.0.0.0:54321** (a high, rarely‑used port) and provides two endpoints:

* `GET /v1/models` – returns a list with the single model `westie-1`.
* `POST /v1/chat/completions` – returns a commit‑message draft (or a static fallback when no Git repository is present).

Example request:

```bash
curl -X POST http://127.0.0.1:54321/v1/chat/completions \
     -H "Content-Type: application/json" \
     -d '{"model":"westie-1","messages":[{"role":"user","content":"Generate a commit message"}]}'
```

Use `pip install --no-cache-dir --index-url https://pypi.org/simple/ Westie=={version}` for update.

## Philosophy

Software should not need an AI service to automate every small task.

Westie investigates whether a focused, transparent, and deterministic program can do one useful thing well: explain code changes in plain language.

---

[![Share](https://img.shields.io/badge/share-000000?logo=x&logoColor=white)](https://x.com/intent/tweet?text=Check%20out%20this%20project%20on%20GitHub:%20https://github.com/livrasand/Westie)
[![Share](https://img.shields.io/badge/share-1877F2?logo=facebook&logoColor=white)](https://www.facebook.com/sharer/sharer.php?u=https://github.com/livrasand/Westie)
[![Share](https://img.shields.io/badge/share-0A66C2?logo=linkedin&logoColor=white)](https://www.linkedin.com/sharing/share-offsite/?url=https://github.com/livrasand/Westie)
[![Share](https://img.shields.io/badge/share-FF4500?logo=reddit&logoColor=white)](https://www.reddit.com/submit?title=Check%20out%20this%20project%20on%20GitHub:%20https://github.com/livrasand/Westie)
[![Share](https://img.shields.io/badge/share-0088CC?logo=telegram&logoColor=white)](https://t.me/share/url?url=https://github.com/livrasand/Westie&text=Check%20out%20this%20project%20on%20GitHub)

*✨ Thanks for visiting **Westie**!*

<img src="https://visitor-badge.laobi.icu/badge?page_id=livrasand.Westie&style=for-the-badge&color=f76f53" alt="Views">
