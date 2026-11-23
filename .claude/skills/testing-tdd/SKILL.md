---
name: Testing & TDD
description: >
  Use when writing tests, practicing test-driven development, designing test suites,
  or deciding what and how to test in any language or framework.
---

# Testing & TDD

Write the test first, watch it fail, make it pass, refactor. Every testing shortcut is a bug you'll debug later.

## When to Use

- Starting a new feature or fixing a bug
- Deciding what level of testing to apply
- Choosing between mocks, stubs, and real dependencies

## The TDD Cycle

| Step | Action | Rule |
|------|--------|------|
| Red | Write a failing test | Must fail for the *right reason* |
| Green | Minimum code to pass | No extra logic, no "while I'm here" |
| Refactor | Clean up code and tests | All tests still pass after cleanup |

Each cycle: 1-5 minutes. Longer means your step is too big.

## Test Design Principles

| Principle | Meaning |
|-----------|---------|
| Test behavior, not implementation | Assert *what* happens, not *how* |
| One assertion per concept | Each test verifies one logical thing |
| Independent and isolated | No test depends on another's state |
| Fast | Unit tests: milliseconds. Slow tests don't get run |

## Mocking Decision Table

| Situation | Approach |
|-----------|----------|
| External API / network call | Mock it |
| Database in unit tests | Mock or in-memory |
| Database in integration tests | Use real instance |
| Pure business logic | No mocks needed |
| Slow or nondeterministic dependency | Mock it |

## Red Flags: Your Tests Are Lying

| Red Flag | What's Wrong |
|----------|-------------|
| Test passes when feature is broken | Testing implementation, not behavior |
| One line change breaks 20 tests | Too coupled to internals |
| Tests pass locally, fail in CI | Hidden environment dependency |
| You mock everything | No integration confidence left |
| 100% coverage but bugs slip through | Covering lines, not edge cases |

## Anti-Rationalization Guide

| Excuse | Reality |
|--------|---------|
| "I'll add tests later" | You won't. Write them now. |
| "Too simple to test" | Simple code calls complex code. Test the boundary. |
| "Tests slow me down" | Debugging without tests is slower. |
| "I'll just test manually" | You'll test it once. Automated tests run forever. |

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Writing tests after the code is done | Write the test first -- it shapes better design |
| Testing private methods directly | Test through the public interface |
| Enormous test setup | Extract builders/factories, simplify the scenario |
| Ignoring flaky tests | Fix or delete immediately -- flaky tests erode trust |
| No test for the bug you fixed | Every bug fix starts with a failing test |

## Attribution
**Original** -- Datatide, MIT licensed. Inspired by [obra/superpowers](https://github.com/obra/superpowers).
