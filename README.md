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

Use `pip install --no-cache-dir --index-url https://pypi.org/simple/ Westie=={version}` for update.

## Philosophy

Software should not need an AI service to automate every small task.

Westie investigates whether a focused, transparent, and deterministic program can do one useful thing well: explain code changes in plain language.
