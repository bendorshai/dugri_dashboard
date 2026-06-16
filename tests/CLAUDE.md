# Tests - CLAUDE.md

## CRITICAL: LLM test files MUST test the production code path

When the production code path changes (e.g. `handle_message` switches from `route_message` to `route_tiered`), ALL LLM test files that test routing/classification MUST be updated to call the same method. Tests that call the old method are testing dead code and give false confidence.

The shared helper `_lazy_optin_helpers._route()` is used by most LLM test files. If the production entry point changes, `_route()` MUST be updated to match. Never leave test helpers pointing at an old code path while production uses a new one.

**Rule: if you change which analyzer method `handle_message` calls, grep for the old method name in all test files and update them immediately. No exceptions.**
