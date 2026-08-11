"""Level-specific summarization prompts + the summarize_fn factory.

This module owns the PROMPTS (one per node level); `traverse.py` owns the tree
walk, content assembly, and ordering. See
docs/superpowers/specs/2026-07-16-summarization-flow-design.md.

The flow computes the repo root TWICE:
  - "root_provisional": a cheap orientation from README/deps/entry-points/tree,
    used only to FRAME the leaves below.
  - "root_final": the trustworthy repo artifact, re-derived from the top-level
    module summaries after all code has been read.

Framing flows DOWN (root -> leaf; root+parent-module -> module); evidence for a
module comes from its LEAF files, never from child-module summaries — so there
is no cycle.

This package stays dependency-free: it receives an already-constructed `relay`
(duck-typed with `.complete_sync(model=, messages=, max_tokens=, system=,
temperature=)` returning an object with a `.text` attribute). The traversal is
synchronous, so we use `complete_sync` — `relay.complete` is a coroutine.
"""
from __future__ import annotations

# Appended to every system prompt: keep output clean for downstream embedding.
FORMATTING = (
    " Output plain prose only: no markdown headers, bold, bullets, or code "
    "fences, and no preamble. Start directly with the substance."
)

# ROOT_PROVISIONAL — simmer-refined (root-level, 5-repo test set, iter 2 → 9.0/10).
# Wins over the seed: hard single-paragraph/3-4-sentence shape (this text is reused
# as framing in every downstream call, so compactness matters) + grounding /
# anti-filename-inference rules. See docs/simmer/root-level/trajectory.md.
ROOT_PROVISIONAL_SYSTEM = (
    "You analyze code repositories and write one tight orientation paragraph in "
    "the repository's own domain vocabulary — concrete and specific, no filler. "
    "This paragraph is reused as framing context for later per-file analysis, so "
    "it must be compact. Output a SINGLE paragraph of 3-4 sentences: no line "
    "breaks between sentences, no markdown headers, bold, bullets, lists, or code "
    "fences, and no preamble — start directly with the substance. Assert only what "
    "the provided content supports; do not invent technologies, integrations, or "
    "maturity/completeness claims it does not show. When naming a specific model, "
    "library, integration, dataset, or speaker, include it only if the README or "
    "manifest explicitly names it — do not infer a name, identity, or purpose from "
    "a file or directory name alone."
)
ROOT_PROVISIONAL_USER = (
    "From the repository content below (README if present, dependency manifest, "
    "entry points, and directory structure — dependencies are a strong domain "
    "signal, and when no README is present infer from the top-level module names "
    "and structure), write ONE paragraph of 3-4 sentences that names the domain "
    "and states: WHAT this repository is and does, WHAT its goals are, and HOW it "
    "works (its main mechanism, stack, or approach). Name concrete components "
    "(libraries, modules, protocols) only when the content shows them. Do not "
    "exceed 4 sentences and do not use more than one paragraph.\n\n{content}"
)

# LEAF — simmer-refined (leaf-level, 9-file/4-language sample, iter 2 → 9.0/10).
# Wins over the seed: requires the third leg (WHAT + HOW + ROLE — the file's role in
# its module/repo and what consumes it, which feeds module synthesis) under a tight
# 2-4-sentence / no-run-on shape. See docs/simmer/leaf-level/trajectory.md.
LEAF_SYSTEM = (
    "You summarize a single source file so a reader understands it without opening "
    "it. Be concrete: name the key functions, classes, or types and the mechanism. "
    "Cover three things: WHAT the file does, HOW it does it, and its ROLE — what it "
    "provides, using only relationships evidenced by the file itself and the "
    "repository context; if its consumers are not shown, do not guess them. Use the "
    "domain vocabulary. Write 2-4 complete "
    "sentences in a single paragraph — never a run-on sentence, and never more than "
    "4 sentences; if the three legs will not fit, keep WHAT and HOW concrete and "
    "state the ROLE in a brief clause rather than expanding it. Output plain prose "
    "only: no markdown headers, bold, bullets, or code fences, and no preamble. "
    "Start directly with the substance."
)
LEAF_USER = (
    "Repository context: {root}\n\n"
    "File path: {path}\n"
    "In 2-4 complete sentences (single paragraph, no run-ons), cover: WHAT this file "
    "does, HOW it does it (name the key functions/classes/types + the mechanism), and "
    "its ROLE — what it provides, using only relationships evidenced by the file and "
    "the repository context above; if its consumers are not shown, say so rather than "
    "guessing. Note notable imports as observed dependencies.\n\n"
    "----- FILE CONTENT -----\n{content}"
)

# MODULE — simmer-refined (module-level, 4-module/3-language frozen-fixture test, iter 1 → 8.7/10).
# Win over the seed: a synthesis guard — the module level never sees source, only child
# summaries, so it must assert only mechanisms/counts/flow/attributions those summaries
# state, preserve each child's exact noun (tool≠agent, tree≠graph), and not drift
# attribution. (A later shape/"be concise" pass REGRESSED — it re-introduced attribution
# drift — so it was rolled back.) See docs/simmer/module-level/trajectory.md.
MODULE_SYSTEM = (
    "You summarize a module (a directory of code) as a unit by synthesizing the "
    "provided child file summaries — you do NOT see the source, only those "
    "summaries. Give the module's collective purpose; do NOT just list files. "
    "Assert only mechanisms, data/control-flow direction, processing order, "
    "component categories, and counts that the child summaries state, and attribute "
    "each capability to the component whose summary states it (do not drift "
    "attribution). Preserve each child's exact noun — a \"tool\" stays a tool (not an "
    "\"agent\"), a \"trait\" is not a \"class\", a hierarchy or tree is not a \"graph\" — and "
    "omit any count or direction the summaries do not state. Use the domain "
    "vocabulary. Write 3-4 sentences in a single paragraph. Output plain prose only: "
    "no markdown headers, bold, bullets, or code fences, and no preamble. Start "
    "directly with the substance."
)
MODULE_USER = (
    "Repository context: {root}\n\n"
    "Parent module context: {parent}\n\n"
    "Module path: {path}\n"
    "Direct sub-modules (by name): {submods}\n\n"
    "Summaries of the files directly in this module:\n{files}\n\n"
    "Synthesize (basing every claim on the child summaries above): WHAT this module "
    "does as a unit, WHAT role it plays, and HOW it is organized. If the summaries "
    "do not state a count, ordering, or flow direction, do not invent one."
)

# ROOT_FINAL — synthesis level, same class as MODULE (reads module summaries, not source).
# Generalizes from the root-provisional shape/grounding + the module synthesis guard
# (preserve nouns, don't invent flow/counts, correct the provisional where modules
# contradict it), allowed a touch fuller (4-6 sentences) as the definitive repo artifact.
# Not separately simmered — it's fed the winner module summaries, so it already improves
# via upward propagation; the guard is applied by analogy from the module layer.
ROOT_FINAL_SYSTEM = (
    "You produce the final intent summary of a repository by synthesizing the "
    "summaries of its top-level modules and files — you do NOT see source, only "
    "those summaries plus a provisional orientation. Assert only what those "
    "summaries support: preserve each module's exact nouns and mechanisms, do not "
    "relabel components or invent repo-wide flow direction, ordering, counts, or "
    "integrations they do not state, and correct anything in the provisional "
    "orientation that the module summaries contradict. Use the repository's domain "
    "vocabulary; be concrete. Write 4-6 complete sentences in a single paragraph — "
    "no run-on sentences, no markdown headers, bold, bullets, or code fences, and no "
    "preamble. Start directly with the substance."
)
ROOT_FINAL_USER = (
    "Provisional orientation (inferred from dependencies/structure only, before "
    "reading code):\n{parent}\n\n"
    "Intent summaries of the repository's top-level modules and files:\n{files}\n\n"
    "Produce the FINAL repository intent, grounded in these summaries: WHAT it "
    "does, its goals, and HOW. Correct anything the provisional guess got wrong, and "
    "do not introduce mechanisms or counts the module summaries do not state."
)

_NO_PARENT = "(none — this is a top-level module; use the repository context above)"

# level -> (system, user_template, max_tokens)
_LEVELS = {
    "root_provisional": (ROOT_PROVISIONAL_SYSTEM, ROOT_PROVISIONAL_USER, 400),
    "leaf": (LEAF_SYSTEM, LEAF_USER, 300),
    "module": (MODULE_SYSTEM, MODULE_USER, 350),
    "root_final": (ROOT_FINAL_SYSTEM, ROOT_FINAL_USER, 450),
}


def make_summarize_fn(relay, model: str):
    """Build a level-dispatching summarize_fn used by `summarize_repo`.

    Call as summarize_fn(level, *, path="", content="", root="", parent=None,
    files="", submods=""). Unused fields for a given level are ignored by that
    level's template. Returns the summary string.
    """

    def summarize_fn(
        level: str,
        *,
        path: str = "",
        content: str = "",
        root: str = "",
        parent: str | None = None,
        files: str = "",
        submods: str = "",
    ) -> str:
        try:
            system, template, max_tokens = _LEVELS[level]
        except KeyError:
            raise ValueError(f"unknown summarization level: {level!r}")

        user = template.format(
            path=path,
            content=content,
            root=root,
            parent=parent if parent is not None else _NO_PARENT,
            files=files or "(no files directly in this module)",
            submods=submods or "(none)",
        )
        response = relay.complete_sync(
            model=model,
            messages=[{"role": "user", "content": user}],
            max_tokens=max_tokens,
            system=system,
            temperature=0.0,
        )
        return response.text.strip()

    return summarize_fn
