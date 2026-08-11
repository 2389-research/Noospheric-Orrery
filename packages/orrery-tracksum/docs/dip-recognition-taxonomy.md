# DIP Recognition Taxonomy
Scaffolding catalog for a small model that reads one tracker DIP and names its node types + design patterns.
Sources: dippin-lang/docs/{GRAMMAR.ebnf,syntax.md,nodes.md,edges.md,context.md} + ~50 real dips across pipelines/ + tracker-runner/pipelines/.

## A. Node kinds (6 first-class; `conditional` exists in grammar but unused in corpus)
- agent — LLM call. fields: prompt, system_prompt, model, provider, max_turns, reasoning_effort(high/med/low), goal_gate(bool), auto_status(bool), response_format/schema, fallback_target, retry_target, max_retries
- tool — shell command:; stdout->ctx.tool_stdout, stderr->ctx.tool_stderr, exit code routes. Used as detectors/gates, ledger/file ops, curl local Ollama.
- human — mode: choice | freeform | interview; default:, questions_key/answers_key
- parallel — fan-out marker: `parallel ID -> A,B,C`
- fan_in — join marker: `fan_in ID <- A,B,C`
- subgraph — embeds another .dip: `ref:` + `params:` (child reads params.*)

Two agent flags that drive routing:
- auto_status:true => engine parses `STATUS:<x>` into ctx.outcome (enables when-ctx.outcome routing)
- goal_gate:true => node is pipeline-critical; non-success fails whole run

Workflow-level: workflow <name>, goal:, start:, exit:, defaults{model,provider,max_retries,max_restarts,restart_target,fidelity,compaction,cache_tools}

## B. Routing constructs (one `edges` block)
`From -> To [when <cond>] [label:<t>] [weight:<int>] [restart:true]`
- when <cond>: string compares over ctx.outcome, ctx.tool_stdout, ctx.last_response, ctx.human_response, graph.goal; ops = == != contains startswith endswith in, not/and/or/parens
- restart:true => back-edge/loop (only legal cycle); clears downstream status+retry, preserves context, ++global restart counter
- max_restarts (defaults) => global loop cap; 20-100 signals loop-heavy pipeline
- weight:N => priority tie-breaker; happy path idiom weight:2
- label: => display + choice key for human mode:choice
- fallback_target (node) => jump when retries exhausted; retry_target => which node re-runs
- precedence: condition -> preferred-label -> suggested-node -> weight -> lexical

## C. Design-pattern catalog (name -> from-the-dip signature -> examples)
1. linear-staged-build — single agent spine A->B->C, no fan-out; stages often goal_gate. (build-codeagent, idea-to-pr, speedrun)
2. gate-then-retry-loop — checker(tool stdout OR agent auto_status): pass->next weight2, fail->producer restart:true. (everywhere)
3. self-retry-per-stage — each X: X->X label:"retry" restart:true beside X->next when success. (doc-writer, speedrun)
4. detect-only-tool-gate vs detect-and-repair-tier — tool check emits status; either continue, or -> agent remediate/verdict that restarts back to the tool check. tool detects / agent repairs / tool re-confirms. (greenfield_review, refactor-express)
5. tournament-fanout-then-select — parallel P->gen_<mA>,gen_<mB>,gen_<mC> (DIFFERENT model:/provider:, each fallback_target:join) -> fan_in -> merge/select. (spec_to_dip, stage_02_tournament, megaplan)
6. cross-critique-matrix — second parallel of critique_<X>_on_<Y> nodes before merge. (stage_02_tournament, spec_to_sprints)
7. parallel-adversarial-review (PAR) — parallel `*_dispatch`->reviewer_a,reviewer_b -> fan_in -> `*_aggregate`(auto_status) -> pass/fail(fix restart). reviewer names encode lens. (iter_run, greenfield_review)
8. model-tiering — upstream opus/gpt reasoning_effort:high, downstream cheap model: (sonnet/flash/qwen). visible from per-node model:+reasoning_effort deltas. (`local_code_gen/*`, iter_run)
9. local-first-with-cloud-escalation — local(qwen) Generate/LocalFix -> CloudFix(cloud agent, fallback_target:Escalate) -> Escalate; status local-exhausted/cloud-handoff. (sprint_exec_qwen, price_ab/offload)
10. graduated-failure-escalation-chain — fix->debug_investigate->replan->failure_summary, each after prior budget-exhaust; success restarts executor. (bug-hunter, refactor-express)
11. budget-guarded-loop — tool check_*_budget inside restart loop; budget_ok->restart, exhausted->exit/escalate; often reset_*_budget on success. (build_from_superpowers, refactor-express, pipeline_from_spec)
12. worklist/ledger loop (sequential map) — tool find_next/check_ledger emits next-<id>/all_done; exec unit; mark_done; restart to find_next. (sprint_runner, iter_run, local_code_gen runners)
13. orchestrator-over-subgraphs — chained subgraph ref: nodes, each + `Check*Output` tool + `*Failed` agent; check_resume/find_next router at top. (greenfield, iter_dev, sprint_runner)
14. spec->sprints->exec decomposition — planner dip ends write_sprint_docs/ledger; separate runner maps sprint_exec over ledger (12+13). (sprint/spec_to_sprints + sprint_runner; local_code_gen/spec_to_sprints)
15. validate->fix->revalidate self-heal — generate_X -> run_validate(tool) -> fix/regenerate -> restart to run_validate; often check_fix_budget. (pipeline_from_spec, spec_to_dip)
16. simmer/iterative-refine loop — judge(auto_status)->refine->revalidate(tool)->restart to judge; often fresh_eyes final gate. (spec_to_dip)
17. tdd/characterization-safety-net — write_tests->run(expect fail)->implement->verify; or Snapshot/Characterization green baseline + savepoint/rollback. (refactor-express)
18. human-approval-gate — human mode:choice, labeled edges; revise->apply_feedback->restart to gate. (plan_gate, 20q, model-debate)
19. phased-fan-out rounds — repeated parallel FanOut/fan_in triples (opening/rebuttal/closing) -> Synthesize + human judge. (model-debate)

## Notes for the summarizer prompt
- Most real dips COMPOSE several patterns — name all that apply.
- Strongest discriminators: distinct model:/provider: across sibling parallel branches (=>tournament/tiering); restart:true edges (=>a loop pattern); auto_status/goal_gate (=>gate); tool nodes emitting status strings (=>detector/gate); subgraph ref: (=>orchestrator/composition).
- `conditional` node kind is unused; branching is always `when` edges.
