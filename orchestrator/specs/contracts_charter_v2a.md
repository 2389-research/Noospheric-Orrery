# Noospheric Orrery: Contract Extraction Spec

**Domain:** `business/legal-compliance/contracts`

**Purpose:** Extraction spec for contracts and agreements — leases, subleases, NDAs, MSAs,
SOWs, and amendments. This spec **replaces** the general spec for this domain. It is the only
spec that runs here, so anything it omits is not extracted at all.

**Design principle:** A contract's value is in its **provisions**, not its proper nouns. The
general spec extracts named things — people, companies, dollar figures — and on an unexecuted
template it therefore extracts almost nothing, even from a document with eighteen fully-worded
provisions. Extract the *structure of the bargain*: who is bound, to what, by when, and what
happens on breach. Do this whether or not the names and figures have been filled in.

---

## Entity Types

| Type | What to extract | Examples |
|------|----------------|---------|
| `party` | A contracting entity together with its defined role in this agreement | "temple cb, llc (landlord)", "okra energy, inc. (tenant)", "sublessor", "subtenant" |
| `signatory` | A named human who signs, consents, guarantees, or witnesses | "jay hooper", "parent/guardian" |
| `organization` | A company or institution named but **not** a party to this agreement | "bank of america", "acme insurance co." |
| `clause` | A provision type, named by its legal function | "indemnification", "assignment and subletting", "no holdover", "entire agreement", "prevailing-party attorney's fees" |
| `monetary_term` | A money amount with the role it plays in the bargain | "base rent $100,000 per month", "security deposit", "liability coverage $300,000" |
| `term_period` | A duration, deadline, or notice window | "initial term december 1 2013 to may 31 2020", "thirty days notice", "within three days" |
| `governing_law` | The stated governing law, jurisdiction, or venue | "california", "state of illinois", "cook county courts" |
| `subject_property` | The specific thing the contract is about | "4350 temple city boulevard, el monte, california", "the leased premises, unit 4b" |
| `location` | A place mentioned that is **not** the subject property | "evanston", "cook county", "illinois" |
| `document` | An **external** instrument referenced or incorporated | "the original lease agreement", "inventory checklist", "exhibit a", "master services agreement" |
| `date_ref` | A specific calendar date | "december 1, 2013", "may 31, 2020" |

### Types deliberately excluded

Do **not** emit these. They were evaluated against real contracts and rejected as noise:

- `topic` and `concept` — on a lease these collect tax-escalation boilerplate ("estate tax",
  "inheritance tax", "capital levy") in high volume and near-zero value.
- `product` — insurance policies named in a coverage clause are not products being bought;
  capture them via `clause` instead.
- `technology`, `event` — no contract role.
- `person` as a bare type — a human is a `signatory`; "landlord" and "tenant" are **roles**,
  and belong to `party`, never to `person`.
- `metric` — superseded by `monetary_term` and `term_period`, which carry the role.
- `obligation` and `condition_trigger` — provision-level spans, not recurring entities. Measured at 228 and 81 instances on one commercial lease, with sentence-length unique names that never merge across documents. Capture the provision as `clause` instead.

### Type Decision Tree

Apply top-to-bottom. First match wins.

1. **`party` vs `organization` vs `signatory`:** Is it bound by this agreement — does the text
   define it as a role ("hereinafter referred to as Landlord")? → `party`. Is it a named human
   affixing a signature or giving consent? → `signatory`. Is it a third party merely mentioned
   (a bank, an insurer, a prior owner)? → `organization`.

2. **`subject_property` vs `location`:** Is it the thing being leased, sold, licensed, or
   transferred? → `subject_property`. Is it any other place — the county for venue, an office
   address for notices? → `location`.

3. **`document` — external only.** An instrument that exists outside this file: an incorporated
   master lease, an attached exhibit, a referenced MSA, a checklist. **Never** an internal
   cross-reference to this contract's own structure. "Article XIII", "Section 4.2",
   "paragraph 7 above" are **not** documents and are not entities at all.

4. **`monetary_term` vs `term_period`:** Money → `monetary_term`. Time → `term_period`. A
   provision like "rent payable on the first day of each month" yields both.

### Custom Type Constraints

Only create a custom `snake_case` type when **both** hold:

1. None of the 11 types above fit — you applied the decision tree and nothing matched.
2. The entity appears 3+ times in the document.

---

## Extraction Rules

### What to Extract

An entity qualifies when **at least one** condition is true:

1. **It is a defined term.** The contract introduces it in quotes, in capitals, or with
   "hereinafter referred to as". Defined terms are the contract's own vocabulary — always
   extract them.

2. **It is a numbered or captioned provision.** Every numbered paragraph, article, or section
   yields at least one `clause`. Name the clause by its legal function, not by its number:
   paragraph 5's "There shall be no holding over" is `no holdover`, not `paragraph 5`.

3. **It is a named party, signatory, place, date, amount, or external document.**

4. **CRITICAL — blanks do not disqualify.** Unexecuted templates are first-class input. When a
   name, amount, or date is a blank line, extract the **role or slot** that the blank sits in
   and leave the value out of the name. `"The sublessor is: ______"` yields
   `party: "sublessor"`. `"a deposit of $______ to cover damages and cleaning"` yields
   `monetary_term: "security deposit"` and `clause: "security deposit"`. A form with every
   blank empty still has its entire provision structure intact — extract all of it.

### What NOT to Extract

1. **Internal cross-references.** "Article XIII", "Section 4.2", "as set forth above",
   "paragraph 7 hereof". These are navigation, not entities.

2. **Boilerplate tax and levy enumerations.** Tax-escalation clauses list every conceivable
   tax ("estate tax", "inheritance tax", "capital levy", "franchise tax"). Extract the single
   `clause: "tax escalation"`, not the list of tax names.

3. **Roles as people.** "Landlord", "tenant", "sublessor" are never `signatory` or `person`.
   They are `party`.

4. **Recitals and throat-clearing.** "WHEREAS the parties desire...", "NOW THEREFORE in
   consideration of the mutual covenants..." — no entities unless a defined term appears.

5. **Bare legal doublets.** "promises, conditions and agreements", "terms, covenants and
   conditions", "successors and assigns" carry no content on their own.

6. **Document furniture.** Page numbers, filing headers ("EX-10 2 lease.htm"), signature-block
   rule lines, "Yes / No" checkboxes.

7. **Severed halves of a compound.** See boundary guidance below.

---

## Entity Boundary Guidance

**`party` — keep the name and its role together as one entity.** `"okra energy, inc. (tenant)"`
is one entity. Do not split it into an organization and a role. When the name is blank, the role
alone is the entity: `"subtenant"`.

**`monetary_term` — keep the amount with its role.** `"base rent $100,000 per month"` is one
entity, not `"$100,000"` plus `"rent"`. When the figure is blank, the role alone:
`"security deposit"`.

**`clause` — one entity per provision, named by function.** A paragraph covering both a deposit
and its refund conditions is `"security deposit"` and `"deposit refund"` — two clauses, because
a reviewer looks for them separately.

---

## Entity Naming Rules

1. **Lowercase**, except that defined terms keep their internal punctuation:
   `"temple cb, llc (landlord)"`.

2. **`clause`: name by legal function, using the conventional term.** `"indemnification"`,
   `"no holdover"`, `"entire agreement"`, `"assignment and subletting"`, `"prevailing-party
   attorney's fees"`, `"condition precedent — landlord consent"`. Never a paragraph number.

3. **`term_period`: preserve the number as written**, including a spelled-out parenthetical:
   `"within three (3) days"`, `"thirty days notice"`.

4. **Do not resolve pronouns into party names** inside an entity name. Rewrite with the role
   instead: `"his guests"` → `"subtenant's guests"`.

5. **Dedup before output.** Each entity appears once.

---

## Worked Example — an unexecuted template

**Input:**

> 6. All charges for utilities connected with premises which are to be paid by the sublessor
> under the master lease shall be paid by the subtenant for the term of this sublease.
>
> 8. Subtenant agrees to pay to sublessor a deposit of $______ to cover damages and cleaning.
> Sublessor agrees that if the premises and contents thereof are returned to him/her in the same
> condition as when received by the subtenant, reasonable wear and tear thereof excepted, (s)he
> will refund to the subtenant $______ at the end of the term, or within 30 days thereafter.

**Output:**

```json
{
  "entities": [
    {"name": "sublessor", "type": "party"},
    {"name": "subtenant", "type": "party"},
    {"name": "utilities allocation", "type": "clause"},
    {"name": "the master lease", "type": "document"},
    {"name": "security deposit", "type": "clause"},
    {"name": "security deposit", "type": "monetary_term"},
    {"name": "deposit refund", "type": "clause"},
    {"name": "within 30 days thereafter", "type": "term_period"}
  ]
}
```

**Why each was extracted:**

| Entity | Condition | Rationale |
|--------|-----------|-----------|
| sublessor, subtenant | #1 defined term, #4 blanks don't disqualify | Names are blank; the **roles** are defined and binding |
| utilities allocation | #2 numbered provision | Paragraph 6 named by function, not number |
| the master lease | #3 external document | Referenced instrument outside this file |
| security deposit (`clause` + `monetary_term`) | #2, #3 | The provision **and** the money slot; amount blank, role survives |
| deposit refund | #2 | Separate clause — a reviewer looks for it separately from the deposit itself |
| within 30 days thereafter | #3 | Deadline, spelled as written |

**NOT extracted:**
- `"$______"` — a blank is not a value; the role `security deposit` carries it
- `"reasonable wear and tear"` — a standard carve-out phrase within the deposit-return condition, not extracted on its own
- `"promises, conditions and agreements"` — bare legal doublet
- `"paragraph 6"`, `"paragraph 8"` — internal cross-references

---

## Output Schema

```json
{
  "entities": [
    {"name": "entity name", "type": "one of the 11 types above"}
  ]
}
```

Flat list of `name + type`. No relationships, no properties, no provenance — the pipeline
handles normalization, dedup, and co-occurrence.

---

## Execution Notes

- **This spec replaces the general pass** for `business/legal-compliance/contracts`. It is
  authored, not simmered; auto-simmer is disabled for this domain. `POST /simmer/business/legal-compliance/contracts`
  refines it on request, seeded from this text.
- **Recall over precision on `clause`.** A missed clause is invisible; a spurious one is visible and easy to reject in the corrections panel.
- **Expect every numbered provision to yield entities.** If a contract has eighteen numbered
  paragraphs and extraction returns three entities, the extraction failed — that is exactly the
  general-spec failure this spec exists to correct.
