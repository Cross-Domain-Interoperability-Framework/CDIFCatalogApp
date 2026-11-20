"""Connects the converters in the CDIF `converters` repository to the harvester.

That repository is a git submodule at server/converters, pinned to a commit. It is a set of
command-line scripts, not a package: each is loaded here from its file, and called through the
function its own `main` uses. In production it should become an installed package; this module
is the only place that would change.

Each function below takes the text of one harvested document and returns one CDIF record. The
converters are asked not to work out conformance themselves (`detect=False`). The catalog does
that once, for every converter alike, with the same code they would have used:
`detect_conformance.py` in the converters' own `validation` submodule (`conformance` below).
Called from here it reads its rule files from this repository, not from GitHub.

Not connected yet, though a converter exists: DCAT (its entry point takes one dataset picked
out of a graph, and a file may hold many) and SDMX (one dataflow out of a structure message).
"""
import importlib.util
import json
import os
import sys
import tempfile
from functools import lru_cache
from pathlib import Path

from app.harvest import HarvestError

# server/converters, beside server/app; /srv/converters in the containers.
ROOT = Path(os.environ.get("CONVERTERS_DIR") or Path(__file__).resolve().parents[2] / "converters")


@lru_cache
def _script(relative: str):
    """Load one converter script as a module. The scripts import their neighbours by bare name,
    so the repository root and the script's own folder go on the import path, as they are when
    the script is run from the command line."""
    path = ROOT / relative
    if not path.is_file():
        raise HarvestError(
            f"{relative} is not installed. Run `git submodule update --init --recursive` in the repository."
        )
    for folder in (str(ROOT), str(path.parent)):
        if folder not in sys.path:
            sys.path.insert(0, folder)
    name = "cdif_converter_" + relative.replace("/", "_").removesuffix(".py").replace("-", "_")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# The content rules detect_conformance holds a claim to, copied from metadataBuildingBlocks (see
# app/profiles/PINNED.md). Given no local copy it would fetch them from GitHub on every record.
SHAPES = Path(__file__).resolve().parents[1] / "conformance"


def conformance(record: dict) -> tuple:
    """The CDIF levels a record's content reaches, as conformance addresses: each level whose
    marks are present in the record and whose content rules the record does not break."""
    module = _script("validation/detect_conformance.py")
    try:
        return tuple(module.detect_cdif_conformance(record, bb_dir=SHAPES))
    except Exception as error:  # the script is not ours; whatever it raises is a failed record
        raise HarvestError(f"Could not work out which CDIF levels the record reaches: {error}") from error


def declare(record: dict, levels) -> dict:
    """Write those levels into the record's catalog record, replacing any CDIF claim there."""
    return _script("validation/detect_conformance.py").apply_conformance(record, list(levels))


def _record(result) -> dict:
    """Converters return the record, or the record with a list of notes about what they did."""
    record = result[0] if isinstance(result, tuple) else result
    if not isinstance(record, dict):
        raise HarvestError("The converter did not produce a record.")
    return record


def _via_file(content: str, suffix: str, convert) -> dict:
    """For converters that read a file path: hand them the document as a temporary file."""
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / f"record{suffix}"
        path.write_text(content, encoding="utf-8")
        return _record(convert(str(path)))


def iso(content: str) -> dict:
    """ISO 19139, ISO 19115-2, ISO 19115-3, or a CSW response wrapping one of them."""
    from lxml import etree

    module = _script("ISO19115/iso_to_cdif.py")
    # no entity expansion and no network: the document comes from a site we do not control
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
    records = module.metadata_records(etree.fromstring(content.encode("utf-8"), parser))
    if len(records) != 1:
        raise HarvestError(f"The file holds {len(records)} ISO metadata records; one record per file is expected.")
    return _record(module.convert_iso_to_cdif(records[0], detect=False))


def schemaorg(content: str) -> dict:
    return _record(_script("soso/ConvertFromSOSO.py").convert_soso_to_cdif(json.loads(content), profile="discovery"))


def croissant(content: str) -> dict:
    return _record(_script("croissant/ConvertFromCroissant.py").convert(json.loads(content)))


def fair2(content: str) -> dict:
    return _record(_script("FAIR2/fair2_to_cdif.py").convert(json.loads(content), detect=False))


def rocrate(content: str) -> dict:
    return _record(_script("ROCrate/ROCrateToCDIF.py").convert_rocrate_to_cdif(json.loads(content), profile="discovery"))


def umm(content: str) -> dict:
    document = json.loads(content)
    meta = None
    if isinstance(document.get("items"), list):  # a CMR search answer wrapping the records
        if len(document["items"]) != 1:
            raise HarvestError(f"The file holds {len(document['items'])} UMM records; one record per file is expected.")
        meta, document = document["items"][0].get("meta"), document["items"][0]["umm"]
    return _record(_script("UMM/umm_to_cdif.py").convert_umm_to_cdif(document, meta=meta, detect=False))


def ddi_122(content: str) -> dict:
    module = _script("DDI/ddi_sssom_to_cdif.py")
    return _via_file(content, ".xml", lambda path: module.convert(path, version="122", detect=False))


def ddi_25(content: str) -> dict:
    module = _script("DDI/ddi_sssom_to_cdif.py")
    return _via_file(content, ".xml", lambda path: module.convert(path, version="25", detect=False))


def ddicdi_xml(content: str) -> dict:
    module = _script("DDI-CDI/ddicdi_to_cdif.py")
    return _via_file(content, ".xml", lambda path: module.convert(path, detect=False))


def ddicdi_jsonld(content: str) -> dict:
    module = _script("DDI-CDI/ddicdi_jsonld_to_cdif.py")
    return _via_file(content, ".jsonld", lambda path: module.convert(path, detect=False))


# format id (from detect.py) -> the function that converts it
CONNECTED = {
    "iso19139": iso,
    "iso19115-2": iso,
    "iso19115-3": iso,
    "csw-response": iso,
    "schemaorg-jsonld": schemaorg,
    "croissant": croissant,
    "fair2": fair2,
    "rocrate": rocrate,
    "umm-c": umm,
    "ddi-1.2.2": ddi_122,
    "ddi-codebook-2.5": ddi_25,
    "ddicdi-xml": ddicdi_xml,
    "ddicdi-jsonld": ddicdi_jsonld,
}
