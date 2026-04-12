"""Golden task definitions for prompt evaluation (P9).

Each golden task is a fixed brief + expected quality signals.
The eval scorer runs the real agent against the brief and checks
whether the output meets the expected signals.

Adding a new golden task:
1. Add an entry to GOLDEN_TASKS with a unique key.
2. Define expected_signals — these are checked by score_output().
3. The brief should be concrete enough that a correct agent produces
   a validatable artifact every time.
"""
from __future__ import annotations

from typing import Any

# key → task definition
GOLDEN_TASKS: dict[str, dict[str, Any]] = {
    "pm_basic_planning": {
        "role": "pm",
        "brief": (
            "Build a Python command-line tool that converts temperatures "
            "between Celsius, Fahrenheit, and Kelvin. "
            "Accept the input value and unit via CLI arguments. "
            "Print the converted values for all other units. "
            "Include at least two pytest tests."
        ),
        "description": "Minimal PM planning task — produces spec and task list for a well-scoped CLI tool.",
        "expected_signals": {
            # artifact types the agent must produce
            "required_artifact_types": ["spec", "tasks"],
            # minimum number of tasks in the tasks artifact
            "min_task_count": 2,
            # keyword that must appear somewhere in the tasks artifact
            "tasks_must_mention": ["celsius", "fahrenheit", "kelvin", "test"],
        },
    },
    "dev_jr_basic_implementation": {
        "role": "dev-jr",
        "brief": (
            "Implement a Python function `word_count(text: str) -> dict[str, int]` "
            "that returns a dictionary mapping each word to its frequency. "
            "Words are case-insensitive. Punctuation attached to words should be stripped. "
            "Include a pytest test file with at least three tests."
        ),
        "description": "Minimal dev-jr task — produces code and tests for a well-scoped function.",
        "expected_signals": {
            "required_artifact_types": ["dev_output"],
            "dev_output_must_have_files": True,
            "dev_output_must_have_test_file": True,
        },
    },
}


def get_golden_task(key: str) -> dict[str, Any]:
    if key not in GOLDEN_TASKS:
        raise KeyError(f"Unknown golden task key: {key!r}. Available: {list(GOLDEN_TASKS)}")
    return GOLDEN_TASKS[key]


def list_golden_task_keys() -> list[str]:
    return list(GOLDEN_TASKS.keys())
