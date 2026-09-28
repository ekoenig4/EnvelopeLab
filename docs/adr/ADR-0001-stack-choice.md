# ADR-0001: Stack choice

- Status: Accepted
- Date: 2026-09-28

## Context
EnvelopeLab needs a typed schema, deterministic serialization, and portable tooling.

## Decision
Use Python 3.11+, Pydantic v2, SQLite, pytest/Hypothesis, and MkDocs.

## Consequences
The stack offers strong validation, straightforward migration support, and low setup overhead.
