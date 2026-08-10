"""The DIP recognition catalog — the single source of truth for dip summarization.

A small model does not reliably *invent* good design-pattern names, but it does
reliably *recognize* against a closed catalog. So the prompt carries the catalog and
the model matches strictly against it. This asset is the reason dip summaries
discriminate between pipelines at all; it was mined from the dippin-lang grammar plus
a corpus of real production dips.

Do NOT retype a "compressed" version of this into a caller. That was tried, and the
condensed copy silently dropped the "strongest discriminators" paragraph, which made
the model report model-tiering as ABSENT on a dip that used it. Import from here.

Provenance and the fuller taxonomy this was distilled from (node kinds, routing
constructs, the pattern survey across ~50 real dips): docs/dip-recognition-taxonomy.md.
"""

DIP_CATALOG = """You recognize design patterns in "DIP" files (a workflow DSL used by the `tracker`
agent runner). A DIP declares named nodes and an `edges` block with conditional routing.
Your ONLY job: read the DIP and name (a) the node kinds it uses and (b) the design
patterns it uses, matching STRICTLY against the catalog below. Do NOT invent pattern
names that aren't in the catalog. If model-tiering / a repair tier / a tournament is
ABSENT, say so — absence is informative.

NODE KINDS: agent(LLM: prompt,model,provider,reasoning_effort,goal_gate,auto_status) |
  tool(shell command:, stdout->ctx.tool_stdout) | human(mode: choice/freeform/interview) |
  parallel(ID -> A,B,C fan-out) | fan_in(ID <- A,B,C join) | subgraph(ref: other.dip).
FLAGS: auto_status:true => STATUS:x parsed into ctx.outcome; goal_gate:true => quality-critical.
EDGES: A->B when <cond> | restart:true (back-edge/loop) | weight:N (happy-path=2) | fallback/max_restarts.

PATTERNS (name -> signature):
linear-staged-build      -> single agent spine A->B->C, no fan-out.
gate-then-retry-loop     -> checker(tool stdout OR agent auto_status); pass->next weight2, fail->producer restart:true.
self-retry-per-stage     -> each X has X->X label:"retry" restart:true beside X->next when success.
tournament-fanout-select -> parallel P->gen_<mA>,gen_<mB> (DIFFERENT model:) -> fan_in -> merge/select.
cross-critique-matrix    -> second parallel of critique_<X>_on_<Y> nodes before merge.
parallel-adversarial-review(PAR) -> parallel *_dispatch->reviewer_a,reviewer_b -> fan_in -> *_aggregate -> pass/fail(fix restart).
model-tiering            -> upstream opus/gpt reasoning_effort:high, downstream cheap model (sonnet/flash/qwen).
local-first-escalation   -> local(qwen) Generate/LocalFix -> CloudFix(cloud agent) -> Escalate.
graduated-failure-chain  -> fix->debug_investigate->replan->failure_summary, each on prior budget-exhaust.
budget-guarded-loop      -> tool check_*_budget inside restart loop; budget_ok->restart, exhausted->exit/escalate.
worklist-ledger-loop     -> find_next/check_ledger emits next-<id>/all_done; exec unit; mark_done; restart to find_next.
orchestrator-subgraphs   -> chained subgraph ref: nodes, each + Check*Output tool + *Failed agent.
spec->sprints->exec      -> planner dip ends write_sprint_docs/ledger; separate runner maps sprint_exec over ledger.
validate-fix-revalidate  -> generate_X -> run_validate(tool) -> fix/regenerate -> restart to run_validate.
simmer-refine-loop       -> judge(auto_status)->refine->revalidate->restart to judge; often fresh_eyes gate.
tdd-characterization     -> write_tests->run(expect fail)->implement->verify; or characterization green baseline.
human-approval-gate      -> human mode:choice, labeled edges; revise->apply_feedback->restart to gate.
phased-fanout-rounds     -> repeated parallel FanOut/fan_in triples -> Synthesize.
detect-only-check        -> a tool check that emits a status string but has NO repair/agent node after it; routes only continue or exit. NAME THIS when a seam/integration check exists with no remediation.
detect-and-repair-tier   -> tool check emits status -> a following AGENT remediate/verdict/repair node -> restart back to the same tool check. NAME THIS ONLY when such a repair agent is present.

Most real dips COMPOSE several patterns — name ALL that apply. Strongest discriminators:
distinct model:/provider: across sibling parallel branches (=>tournament/tiering); restart:true edges (=>a loop);
auto_status/goal_gate (=>gate); tool nodes emitting status strings (=>detector/gate); subgraph ref: (=>composition).

OUTPUT exactly these three sections:
NODE KINDS: <comma list of kinds present>
PATTERNS: <bulleted list; each = pattern-name — one-line evidence (node/edge names) from THIS dip>
SUMMARY: <2-3 sentences: the architecture in plain terms, incl. what is notably ABSENT>
"""
