"""Connects the converters in the CDIF `converters` repository to the harvester.

That repository is a git submodule at server/converters, pinned to a commit. It is a set of
command-line scripts, not a package: each is loaded here from its file, and called through the
function its own `main` uses. In production it should become an installed package; this module
is the only place that would change.

Each function below takes the text of one harvested document and returns one CDIF record. The
converters are asked not to work out conformance themselves (`detect=False`). The catalog does
that once, for every converter alike, with the same code they would have used:
`detect_conformance.py` in the converters' own `validation` submodule (`conformance` below).
Which profiles it looks for is set in app/profile-sources.yaml. Called from here it reads its
rule files from this repository, not from GitHub.

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

import yaml

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


APP = Path(__file__).resolve().parents[1]


@lru_cache
def sources() -> dict:
    """The groups of profiles to look for, from app/profile-sources.yaml: only those switched
    on, in the order written. Each group's folder holds one conformance.json per profile, copied
    from the building block repository that defines it (see app/conformance/PINNED.md), and any
    rule files those name. Given no local copy the script would fetch rule files from GitHub on
    every record."""
    listed = yaml.safe_load((APP / "profile-sources.yaml").read_text(encoding="utf-8"))
    return {name: {**group, "folder": APP / group["folder"]} for name, group in listed.items() if group["enabled"]}


def conformance(record: dict) -> tuple:
    """The profiles a record's content reaches, as conformance addresses: each profile, in the
    groups switched on, whose marks are present in the record, whose content rules the record
    does not break, and whose own requirements are among what was found before it."""
    module = _script("validation/detect_conformance.py")
    found = []
    try:
        for group in sources().values():
            if "claims_under" in group:
                found += module.detect_domain_conformance(
                    record, found, group["folder"], manage_prefix=group["claims_under"]
                ).declared
            else:
                found += module.detect_cdif_conformance(record, bb_dir=group["folder"], use_bb_source=True)
    except Exception as error:  # the script is not ours; whatever it raises is a failed record
        raise HarvestError(f"Could not work out which profiles the record reaches: {error}") from error
    return tuple(found)


def declare(record: dict, found) -> dict:
    """Write those addresses into the record's catalog record, replacing any claim there to a
    profile in a group that was looked for. Other claims are kept."""
    module = _script("validation/detect_conformance.py")
    module.apply_conformance(record, [u for u in found if u.startswith(module.CDIF_BASE)])
    for group in sources().values():
        prefix = group.get("claims_under", module.CDIF_BASE)
        if not prefix.startswith(module.CDIF_BASE):
            module.apply_conformance(record, [u for u in found if u.startswith(prefix)], manage_prefix=prefix, append=True)
    return record


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


def datacite(content: str) -> dict:
    """DataCite XML, kernel 3 or 4: one record on its own."""
    from lxml import etree

    module = _script("DataCite/datacite_to_cdif.py")
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
    records = module.resources(etree.fromstring(content.encode("utf-8"), parser))
    if len(records) != 1:
        raise HarvestError(f"The file holds {len(records)} DataCite records; one record per file is expected.")
    return _record(module.convert_datacite_to_cdif(records[0], detect=False))


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


# framed=True: one record rooted at the dataset, each code list embedded where it is first used,
# instead of a graph of the dataset and its code lists as separate nodes (converters issue 38).
def ddi_122(content: str) -> dict:
    module = _script("DDI/ddi_sssom_to_cdif.py")
    return _via_file(content, ".xml", lambda path: module.convert(path, version="122", detect=False, framed=True))


def ddi_25(content: str) -> dict:
    module = _script("DDI/ddi_sssom_to_cdif.py")
    return _via_file(content, ".xml", lambda path: module.convert(path, version="25", detect=False, framed=True))


def ddicdi_xml(content: str) -> dict:
    module = _script("DDI-CDI/ddicdi_to_cdif.py")
    return _via_file(content, ".xml", lambda path: module.convert(path, detect=False))


def ddicdi_jsonld(content: str) -> dict:
    module = _script("DDI-CDI/ddicdi_jsonld_to_cdif.py")
    return _via_file(content, ".jsonld", lambda path: module.convert(path, detect=False))


def _xml_root(content: str):
    """The document's root element. No entity expansion and no network: the document comes from
    a site we do not control."""
    from lxml import etree

    return etree.fromstring(content.encode("utf-8"), etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False))


def _only(found: list, kind: str):
    if len(found) != 1:
        raise HarvestError(f"The file holds {len(found)} {kind} records; one record per file is expected.")
    return found[0]


# These five know nothing of where the file came from. Each can be told (the record's own
# address, the address of the service), and makes up an identifier when the document names none.
def dublin_core(content: str) -> dict:
    """Dublin Core as a CSW record or an OAI-PMH oai_dc record."""
    module = _script("DublinCore/dc_to_cdif.py")
    return _record(module.convert_dc_to_cdif(_only(module.records(_xml_root(content)), "Dublin Core"), detect=False))


def eml(content: str) -> dict:
    module = _script("EML/eml_to_cdif.py")
    return _record(module.convert_eml_to_cdif(_only(module.documents(_xml_root(content)), "EML"), detect=False))


def fgdc(content: str) -> dict:
    module = _script("FGDC/fgdc_to_cdif.py")
    return _record(module.convert_fgdc_to_cdif(_only(module.documents(_xml_root(content)), "FGDC"), detect=False))


def ogc_capabilities(content: str) -> dict:
    """What a WMS or WFS says about itself. The converter refuses the other OGC services."""
    return _record(_script("OGCServices/ogc_services_to_cdif.py").convert_capabilities_to_cdif(_xml_root(content), detect=False))


def stac(content: str) -> dict:
    """A STAC Collection. The converter refuses an Item or a Catalog."""
    return _record(_script("STAC/stac_to_cdif.py").convert_stac_to_cdif(json.loads(content), detect=False))


# format id (from detect.py) -> the function that converts it
CONNECTED = {
    "iso19139": iso,
    "iso19115-2": iso,
    "iso19115-3": iso,
    "csw-response": iso,
    "datacite-xml": datacite,
    "schemaorg-jsonld": schemaorg,
    "croissant": croissant,
    "fair2": fair2,
    "rocrate": rocrate,
    "umm-c": umm,
    "ddi-1.2.2": ddi_122,
    "ddi-codebook-2.5": ddi_25,
    "ddicdi-xml": ddicdi_xml,
    "ddicdi-jsonld": ddicdi_jsonld,
    "dublin-core": dublin_core,
    "eml": eml,
    "fgdc": fgdc,
    "ogc-capabilities": ogc_capabilities,
    "stac": stac,
}
