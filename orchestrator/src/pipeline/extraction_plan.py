# ABOUTME: Decides which extraction passes run for a document's domains.
# ABOUTME: An authored spec is complete and suppresses the general pass; a simmered one is not.

from ..repositories.interfaces import Spec


def resolve_extraction_plan(store, domains: list[str]) -> tuple[bool, list[Spec]]:
    """Resolve the extraction passes for a document assigned to `domains`.

    Returns `(run_general, specs)`.

    Walks each domain's ancestors deepest-first and collects every spec found,
    deduplicated by spec id — a spec shared by two of the document's domains runs once.

    `run_general` is False when any resolved spec is authored. The two spec sources carry
    different CONTRACTS, and the distinction is load-bearing:

      - a SIMMERED domain spec is additive by design (see worker/src/jobs/simmer_domain.py:
        "general spec handles the base types"). Suppressing the general pass alongside one
        would silently drop every base entity type.
      - an AUTHORED spec is a domain expert's complete declaration of what matters. Running
        the general pass alongside it would reintroduce exactly the entities they excluded.

    So the rule is narrow on purpose: general is skipped ONLY when an authored spec applies.
    """
    specs: list[Spec] = []
    seen_specs: set[str] = set()

    for domain_path in domains:
        parts = domain_path.split("/")
        ancestor_paths = ["/".join(parts[:i + 1]) for i in range(len(parts))]
        for ancestor in reversed(ancestor_paths):  # deepest first
            domain_spec = store.specs.get_for_domain(ancestor)
            if domain_spec and domain_spec.id not in seen_specs:
                seen_specs.add(domain_spec.id)
                specs.append(domain_spec)

    run_general = not any(s.source == "authored" for s in specs)
    return run_general, specs
