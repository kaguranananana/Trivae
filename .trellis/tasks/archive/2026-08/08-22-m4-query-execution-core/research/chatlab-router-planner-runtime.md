# ChatLab Reference Research

## Scope

GitHub research was limited to the current ChatLab router/planner/runtime implementation as a reference. Trivae's ADR explicitly says to reuse principles and failure lessons, not copy business heuristics.

## Observations

- ChatLab currently models three routes (`direct_response`, `tool_assisted`, `planned_execution`) and contains domain-specific keyword heuristics. Trivae intentionally keeps two routes because its first query core has one standard tool path and one optional planned guidance path.
- ChatLab's planner validates structured output, bounds plan size, filters available tools and treats guidance as non-executable plan data. These are useful implementation principles.
- ChatLab counts tool rounds at a turn boundary and has an SDK-level max-turn guard. Trivae separates its product tool-round budget from the SDK absolute backstop and exposes both outcomes explicitly.
- ChatLab event mapping demonstrates the value of stable content/tool/turn/usage events, but Trivae must project its own event contract and never leak SDK payloads.

## Deliberate differences

- No direct-response route is introduced.
- No business-keyword list is copied into Trivae; route rules use structural signals and include a regression case for a simple structured statistic containing “分析”.
- No ChatLab workflow executor, replan loop, session state or provider-specific behavior is imported.
