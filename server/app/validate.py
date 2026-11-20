"""Decides whether a record is a valid CDIF record, and says what is wrong in plain words.

Two checks, both using files copied from metadataBuildingBlocks (see profiles/PINNED.md):
the profile's JSON Schema, then its SHACL rules. A schema failure is always a violation; a SHACL
result keeps the severity its rule was written with (violation, warning or information).

The form does not hold everything a record needs. `prepare` adds what the author never sees:
the prefixes, an identifier for the record, and the catalog record entry with the profile's
conformance declaration. Those are read from the schema, not written here, so they follow the
schema when its version changes.
"""
import copy
import datetime
import json
import re
import uuid
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, HTTPException
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import BaseModel
from rdflib import BNode, Graph, Namespace, URIRef
from rdflib.namespace import RDF

PROFILE_DIR = Path(__file__).parent / "profiles"
MESSAGE_DIR = Path(__file__).parent / "messages"
SH = Namespace("http://www.w3.org/ns/shacl#")
SEVERITY = {SH.Violation: "violation", SH.Warning: "warning", SH.Info: "info"}
CONFORMANCE_PREFIX = "https://w3id.org/cdif/"

router = APIRouter(prefix="/api")


@lru_cache
def load(profile: str) -> dict:
    """The schema and shapes for a profile, plus what `prepare` needs from the schema."""
    folder = PROFILE_DIR / profile
    schema = json.loads((folder / "schema.json").read_text(encoding="utf-8"))
    shapes = Graph().parse(folder / "rules.shacl", format="turtle")
    context_schema = schema["properties"]["@context"]["properties"]
    return {
        "validator": Draft202012Validator(schema, format_checker=FormatChecker()),
        "shapes": shapes,
        # prefix -> the namespace the schema pins it to
        "prefixes": {p: s["const"] for p, s in context_schema.items() if "const" in s},
        "fields": [p for p in schema["properties"] if not p.startswith("@")],
        "conformance": sorted(_conformance_uris(schema["properties"]["schema:subjectOf"])),
    }


@lru_cache
def plain_messages(profile: str) -> dict:
    """Each rule's message -> the same thing in plain words (messages/<profile>.json). The rules
    are written for people who know the schema; the report is read by people who do not. A rule
    with no entry keeps its own wording, and a test fails until it has one."""
    path = MESSAGE_DIR / f"{profile}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def _conformance_uris(node, inside=False) -> set:
    """Every profile address the schema requires under dcterms:conformsTo."""
    found = set()
    if isinstance(node, dict):
        for key, value in node.items():
            if inside and key == "const" and isinstance(value, str) and value.startswith(CONFORMANCE_PREFIX):
                found.add(value)
            found |= _conformance_uris(value, inside or key == "dcterms:conformsTo")
    elif isinstance(node, list):
        for item in node:
            found |= _conformance_uris(item, inside)
    return found


def profile_for(conforms_to, default: str) -> str:
    """The installed profile to validate a record against, from what its own catalog record says
    it conforms to: the profile that asks for the most of those addresses, all of which the
    record declares. A record declaring nothing we hold a profile for gets the default."""
    declared = set(conforms_to)
    best, size = default, 0
    for folder in sorted(PROFILE_DIR.iterdir()):
        if (folder / "schema.json").is_file():
            wanted = set(load(folder.name)["conformance"])
            if wanted and wanted <= declared and len(wanted) > size:
                best, size = folder.name, len(wanted)
    return best


def declare(profile: str, record: dict) -> dict:
    """Add the profile's conformance addresses to a record's catalog record, keeping what is
    there. For a record the catalog itself produced by converting another format: the claim is
    the catalog's to make, and it is only published if the check that follows bears it out."""
    about = record.get("schema:subjectOf")
    if not isinstance(about, dict):
        return record  # no catalog record to add to; the check will say so
    listed = about.get("dcterms:conformsTo")
    listed = listed if isinstance(listed, list) else ([listed] if listed else [])
    have = {(c.get("@id") if isinstance(c, dict) else c) for c in listed}
    about["dcterms:conformsTo"] = listed + [{"@id": uri} for uri in load(profile)["conformance"] if uri not in have]
    return record


def strip_empty(value):
    """Remove what the form leaves behind for untouched fields: blank text, empty lists, and
    objects holding nothing but a type marker. Returns None when nothing is left."""
    if isinstance(value, str):
        return value if value.strip() else None
    if isinstance(value, list):
        items = [x for x in (strip_empty(v) for v in value) if x is not None]
        return items or None
    if isinstance(value, dict):
        out = {k: x for k, x in ((k, strip_empty(v)) for k, v in value.items()) if x is not None}
        if not any(k not in ("@type", "@context") for k in out):
            return None
        # The form holds a type as one word; the schema wants a list of them.
        if isinstance(out.get("@type"), str):
            out["@type"] = [out["@type"]]
        return out
    return value


def prepare(profile: str, document: dict, record_id: str | None = None) -> dict:
    """The form's document as a complete record: empties removed, server-owned parts added."""
    spec = load(profile)
    context = dict(document.get("@context") or {})
    record = strip_empty({k: v for k, v in document.items() if k != "@context"}) or {}
    record = copy.deepcopy(record)

    # The form holds each access condition as a group of fields, and the schema takes such a
    # group only when it has a web address. One with no address is a plain statement, which the
    # schema takes as text.
    conditions = record.get("schema:conditionsOfAccess")
    if isinstance(conditions, list):
        record["schema:conditionsOfAccess"] = [
            ": ".join(c[k] for k in ("schema:name", "schema:description") if c.get(k))
            if isinstance(c, dict) and c.get("schema:name") and not c.get("schema:url") else c
            for c in conditions
        ]

    record["@context"] = {**context, **spec["prefixes"]}
    record.setdefault("@type", ["schema:Dataset"])
    record.setdefault("@id", f"urn:uuid:{record_id or uuid.uuid4()}")

    # The catalog record is the server's statement about the record, so the server writes its
    # identity, what it describes, and which profiles it claims. The author's own entries
    # (maintainer, source catalog) are kept.
    about = record.get("schema:subjectOf") or {}
    about["@type"] = ["schema:Dataset"]
    about["@id"] = f"{record['@id']}#metadata" if not record["@id"].startswith("urn:") else (
        f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, record['@id'])}"
    )
    about["schema:additionalType"] = [{"@id": "dcat:CatalogRecord"}]
    about["schema:about"] = {"@id": record["@id"]}
    about["dcterms:conformsTo"] = [{"@id": uri} for uri in spec["conformance"]]
    about.setdefault("schema:sdDatePublished", datetime.date.today().isoformat())
    record["schema:subjectOf"] = about
    return record


# ---- JSON Schema ----------------------------------------------------------------------------

TYPE_WORDS = {
    "string": "text",
    "array": "a list",
    "object": "a group of fields",
    "number": "a number",
    "integer": "a whole number",
    "boolean": "yes or no",
}
FORMAT_WORDS = {
    "date": "must be a full date written like 2024-03-30",
    "date-time": "must be a date and time written like 2024-03-30T14:00:00Z",
    "uri": "must be a web address or other identifier starting with a scheme, such as https://",
    "iri": "must be a web address or other identifier starting with a scheme, such as https://",
    "email": "must be an email address",
}


def _is_branch_choice(error) -> bool:
    """An error that only says "this is not that kind of thing": a type marker that did not match."""
    return bool(error.absolute_path) and error.absolute_path[-1] in ("@type", "@id") and error.validator in (
        "const", "enum", "contains",
    )


def _leaves(error):
    """The errors that name an actual problem. A failed choice between shapes (anyOf/oneOf) is
    one error whose message names nothing; the real ones are in its context."""
    if not error.context:
        return [error]
    out = []
    for sub in error.context:
        out.extend(_leaves(sub))
    return out


def _best_leaves(error):
    leaves = _leaves(error)
    if len(leaves) == 1:
        return leaves
    real = [e for e in leaves if not _is_branch_choice(e)] or leaves
    # Each alternative shape reports its own complaints. Keep those of the alternative the value
    # came closest to: the one whose complaints sit deepest, then the one with fewest of them.
    by_branch = {}
    for e in real:
        branch = tuple(e.absolute_schema_path)[: len(error.absolute_schema_path) + 2]
        by_branch.setdefault(branch, []).append(e)
    best = max(by_branch.values(), key=lambda es: (max(len(e.absolute_path) for e in es), -len(es)))
    return best


def _say(error) -> tuple[list, str]:
    """(path to the value, plain-words message) for one schema error."""
    path = list(error.absolute_path)
    v, want = error.validator, error.validator_value
    if v == "required":
        missing = [p for p in want if p not in error.instance]
        return path + missing[:1], "is missing"
    if v == "type":
        kinds = want if isinstance(want, list) else [want]
        return path, "should be " + " or ".join(TYPE_WORDS.get(k, k) for k in kinds)
    if v == "format":
        return path, FORMAT_WORDS.get(want, f"is not a valid {want}")
    if v == "minItems":
        return path, "needs at least one entry" if want == 1 else f"needs at least {want} entries"
    if v == "minLength":
        return path, "is empty" if want == 1 else f"must be at least {want} characters long"
    if v in ("enum", "const"):
        allowed = want if v == "enum" else [want]
        return path, "must be " + (" or ".join(str(a) for a in allowed) if len(allowed) <= 6 else "one of the listed values")
    if v == "pattern":
        return path, "is not written in the expected form"
    if v == "contains":
        return path, "is missing an entry the profile requires"
    if v == "additionalProperties":
        extra = sorted(set(error.instance) - set(error.schema.get("properties", {})))
        return path + extra[:1], "is not allowed here"
    if v in ("anyOf", "oneOf"):
        return path, "does not match any of the shapes allowed here"
    return path, error.message[:200]


def _alternatives(error):
    """For "one of these fields must be present": the field names, else None."""
    leaves = [e for e in _leaves(error) if not _is_branch_choice(e)]
    if len(leaves) < 2 or any(e.validator != "required" or e.absolute_path != error.absolute_path for e in leaves):
        return None
    names = []
    for e in leaves:
        names += [p for p in e.validator_value if p not in e.instance and p not in names]
    return names if len(names) > 1 else None


def schema_findings(spec: dict, record: dict) -> list[dict]:
    seen, out = set(), []
    for error in spec["validator"].iter_errors(record):
        names = _alternatives(error)
        if names:
            out.append({
                "severity": "violation", "source": "schema",
                "path": list(error.absolute_path) + names[:1], "message": "is missing",
                "alternatives": names,
            })
            continue
        for leaf in _best_leaves(error):
            path, message = _say(leaf)
            key = (tuple(path), message)
            if key in seen:
                continue
            seen.add(key)
            out.append({"severity": "violation", "source": "schema", "path": path, "message": message})
    return out


# ---- SHACL ----------------------------------------------------------------------------------


def _compact(iri: str, prefixes: dict) -> str:
    for prefix, namespace in sorted(prefixes.items(), key=lambda kv: -len(str(kv[1]))):
        if isinstance(namespace, str) and iri.startswith(namespace):
            return f"{prefix}:{iri[len(namespace):]}"
    return iri


def _path_from_root(graph: Graph, root, focus, prefixes: dict) -> list | None:
    """The chain of properties leading from the record to a node, so a finding about a nested
    node (an author, a distribution) can be shown against the field that holds it."""
    if focus == root:
        return []
    trail, queue = {root: []}, [root]
    while queue:
        node = queue.pop(0)
        for p, o in graph.predicate_objects(node):
            if p in (RDF.first, RDF.rest):
                step = []  # list plumbing, not a field
            elif p == RDF.type:
                continue
            else:
                step = [_compact(str(p), prefixes)]
            if isinstance(o, (URIRef, BNode)) and o not in trail:
                trail[o] = trail[node] + step
                if o == focus:
                    return trail[o]
                queue.append(o)
    return None


def _field_named_in(message: str, fields: list) -> list:
    """A rule about the record as a whole names no field, but its wording usually does
    ("schema:url", "licenses"). A finding that points somewhere is more use than one that does
    not, so take the field mentioned first. This is a guess from the wording, used only when the
    rule gives nothing better."""
    text = message.lower()
    hits = []
    for field in fields:
        local = field.split(":")[-1].lower()
        for needle in (field.lower(), local if len(local) > 3 else None):
            if needle and needle in text:
                hits.append((text.index(needle), field))
                break
    return [min(hits)[1]] if hits else []


def shacl_findings(spec: dict, record: dict, plain: dict | None = None) -> list[dict]:
    import pyshacl

    plain = plain or {}

    data = Graph().parse(data=json.dumps(record), format="json-ld")
    _, report, _ = pyshacl.validate(
        data, shacl_graph=spec["shapes"], advanced=True, inference="none", allow_warnings=True
    )
    # A harvested record may lack either of these; the schema check reports that, and this one
    # must not fall over on it.
    prefixes = record.get("@context") if isinstance(record.get("@context"), dict) else {}
    root = URIRef(record["@id"]) if isinstance(record.get("@id"), str) else None
    seen, out = set(), []
    for result in report.subjects(RDF.type, SH.ValidationResult):
        focus = report.value(result, SH.focusNode)
        result_path = report.value(result, SH.resultPath)
        path = _path_from_root(data, root, focus, prefixes) if root is not None else None
        if path is None:
            path = []
        if isinstance(result_path, URIRef):
            path = path + [_compact(str(result_path), prefixes)]
        message = " ".join(str(report.value(result, SH.resultMessage) or "").split())
        if not path:
            path = _field_named_in(message, spec["fields"])  # from the rule's own wording
        message = plain.get(message, message)
        severity = SEVERITY.get(report.value(result, SH.resultSeverity), "violation")
        key = (severity, tuple(path), message)
        if key in seen:  # the same rule is declared in more than one building block
            continue
        seen.add(key)
        out.append({"severity": severity, "source": "rules", "path": path, "message": message})
    return out


# ---- Report ---------------------------------------------------------------------------------

ORDER = {"violation": 0, "warning": 1, "info": 2}


def _where(path: list) -> str:
    """The part of a path below the top-level field, in words: "entry 2, name"."""
    words = []
    for step in path[1:]:
        if isinstance(step, int):
            words.append(f"entry {step + 1}")
        elif step != "@list":
            local = step.split(":")[-1].lstrip("@")
            words.append(re.sub(r"(?<=[a-z])(?=[A-Z])", " ", local).lower())
    return ", ".join(words)


def _merge(schema: list, rules: list) -> list:
    """Both checks often report the same problem. Keep one: the rule's own sentence when the
    schema only says a field "is missing", the schema's when it says something specific."""
    # the graph the rules read has no entry numbers, so compare paths without them
    norm = lambda path: tuple(step for step in path if isinstance(step, str) and step != "@list")
    rule_violations = {norm(f["path"]) for f in rules if f["severity"] == "violation"}
    schema_kept = []
    for f in schema:
        same = {norm(f["path"][:-1] + [name]) for name in f.get("alternatives") or f["path"][-1:]}
        if not (f["message"] == "is missing" and same & rule_violations):
            schema_kept.append(f)
    covered = {norm(f["path"]) for f in schema_kept}
    rules_kept = [f for f in rules if not (f["severity"] == "violation" and norm(f["path"]) in covered)]
    return schema_kept + rules_kept


def check_record(profile: str, record: dict) -> dict:
    """Validate a complete record as it stands. Harvested records come this way: they already
    carry their own identifier and catalog record, which must not be rewritten."""
    spec = load(profile)
    findings = schema_findings(spec, record)
    # SHACL reads the record as a graph. If the schema already rejected it the graph may not
    # mean what the author intended, but its advice about missing recommended fields still helps.
    findings = _merge(findings, shacl_findings(spec, record, plain_messages(profile)))
    for f in findings:
        f["property"] = f["path"][0] if f["path"] else None
        f["where"] = _where(f["path"])
    findings.sort(key=lambda f: (ORDER[f["severity"]], str(f["property"])))
    counts = {s: sum(f["severity"] == s for f in findings) for s in ORDER}
    return {"valid": counts["violation"] == 0, "counts": counts, "findings": findings, "record": record}


def check(profile: str, document: dict, record_id: str | None = None) -> dict:
    """Validate a document from the form, after completing it into a record."""
    return check_record(profile, prepare(profile, document, record_id))


class CheckRequest(BaseModel):
    profile: str
    document: dict
    id: str | None = None


@router.post("/validate")
def validate(body: CheckRequest) -> dict:
    if not (PROFILE_DIR / body.profile / "schema.json").is_file() or not body.profile.isalnum():
        raise HTTPException(422, f"Unknown profile: {body.profile}")
    return check(body.profile, body.document, body.id)
