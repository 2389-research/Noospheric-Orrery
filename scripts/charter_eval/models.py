# ABOUTME: The harness/metrics data contract. Frozen so metric functions cannot mutate
# ABOUTME: collected results, and JSON-round-trippable so collection and scoring can run
# ABOUTME: at different times (collection needs a live LLM; scoring does not).
from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class TypeResult:
    type: str
    count: int
    names: tuple[str, ...]


@dataclass(frozen=True)
class DocResult:
    doc_id: str
    instrument: str
    executed: bool
    variant: str
    repeat: int
    primary_domain: str
    run_general: bool
    specs_applied: tuple[str, ...]
    latency_s: float
    types: tuple[TypeResult, ...]

    @classmethod
    def from_response(cls, doc_id, instrument, executed, variant, repeat,
                      latency_s, payload: dict) -> "DocResult":
        types = tuple(
            TypeResult(type=t["type"], count=t["count"], names=tuple(t.get("names") or ()))
            for t in payload.get("entity_types", [])
        )
        return cls(
            doc_id=doc_id, instrument=instrument, executed=executed,
            variant=variant, repeat=repeat,
            primary_domain=payload.get("primary_domain", ""),
            run_general=bool(payload.get("run_general")),
            specs_applied=tuple(payload.get("specs_applied") or ()),
            latency_s=latency_s, types=types,
        )

    def names_for(self, type_: str) -> tuple[str, ...]:
        for t in self.types:
            if t.type == type_:
                return t.names
        return ()

    def count_for(self, type_: str) -> int:
        """The reported count for `type_`, which is NOT len(names_for(type_)).

        `names` is empty whenever the ingest response was fetched without
        `full_names=true`, but `count` is always populated — so any count-based
        metric (M3, M5) must read this, not the length of the name tuple.
        """
        for t in self.types:
            if t.type == type_:
                return t.count
        return 0

    def fired_types(self) -> frozenset[str]:
        return frozenset(t.type for t in self.types if t.count > 0)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "DocResult":
        return cls(
            **{**d,
               "specs_applied": tuple(d["specs_applied"]),
               "types": tuple(TypeResult(type=t["type"], count=t["count"],
                                         names=tuple(t["names"])) for t in d["types"])},
        )
