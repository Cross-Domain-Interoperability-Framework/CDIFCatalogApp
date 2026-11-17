"""Mapping from registry responses to CDIF shapes. No network: the inputs are written out here,
following the field names the live services returned on 2026-11-17."""
import pytest
from fastapi import HTTPException

from app import lookup

DATACITE = {
    "data": {
        "attributes": {
            "doi": "10.5555/example-1",
            "titles": [
                {"title": "Autre titre", "titleType": "TranslatedTitle"},
                {"title": "Zircon U–Pb ages, Río Grande rift", "titleType": None},
            ],
            "creators": [
                {
                    "name": "Ortiz, María",
                    "nameType": "Personal",
                    "givenName": "María",
                    "familyName": "Ortiz",
                    "affiliation": ["Example University"],
                    "nameIdentifiers": [
                        {"nameIdentifier": "https://orcid.org/0000-0002-1825-0097", "nameIdentifierScheme": "ORCID"}
                    ],
                },
                {
                    "name": "Example Working Group",
                    "nameType": "Organizational",
                    "givenName": None,
                    "familyName": None,
                    "affiliation": [],
                    "nameIdentifiers": [],
                },
                {
                    "name": "Lee, K.",
                    "nameType": "Personal",
                    "affiliation": [{"name": "Institute of Rocks", "affiliationIdentifier": "https://ror.org/000000000"}],
                    "nameIdentifiers": [{"nameIdentifier": "12345", "nameIdentifierScheme": "ISNI"}],
                },
            ],
            "publisher": {"name": "Example Repository"},
            "publicationYear": 2024,
            "dates": [
                {"date": "2024-03-30", "dateType": "Issued"},
                {"date": "2025", "dateType": "Updated"},
            ],
            "descriptions": [
                {"description": "How it was made.", "descriptionType": "Methods"},
                {"description": "Ages of 40 zircons.", "descriptionType": "Abstract"},
            ],
            "rightsList": [{"rights": "CC BY 4.0", "rightsUri": "https://creativecommons.org/licenses/by/4.0/"}],
            "subjects": [{"subject": "geochronology"}, {"subject": "zircon"}],
            "url": "https://repository.example/records/1",
            "language": "en",
            "version": "2.1",
            "updated": "2026-07-09T14:34:39.000Z",
        }
    }
}


def test_datacite_maps_to_the_form_shapes():
    r = lookup.datacite_to_cdif(DATACITE)
    assert r["schema:name"] == "Zircon U–Pb ages, Río Grande rift"  # the untyped title, not the translation
    assert r["schema:description"] == "Ages of 40 zircons."  # the abstract, not the methods
    assert r["schema:identifier"] == "https://doi.org/10.5555/example-1"
    assert r["schema:url"] == "https://repository.example/records/1"
    assert r["schema:datePublished"] == "2024-03-30"
    assert r["schema:keywords"] == ["geochronology", "zircon"]
    assert r["schema:license"] == [
        {"@type": "schema:CreativeWork", "schema:name": "CC BY 4.0", "schema:url": "https://creativecommons.org/licenses/by/4.0/"}
    ]
    assert r["schema:publisher"] == {"@type": "schema:Organization", "schema:name": "Example Repository"}
    assert r["schema:creator"] == {
        "@list": [
            {
                "@type": "schema:Person",
                "schema:name": "María Ortiz",
                "schema:identifier": "https://orcid.org/0000-0002-1825-0097",
                "schema:affiliation": {"schema:name": "Example University"},
            },
            {"@type": "schema:Organization", "schema:name": "Example Working Group"},
            # no given/family split, an affiliation object, and an identifier that is not an ORCID
            {"@type": "schema:Person", "schema:name": "Lee, K.", "schema:affiliation": {"schema:name": "Institute of Rocks"}},
        ]
    }


def test_datacite_does_not_invent_a_modified_date():
    # "Updated: 2025" is only a year, and the record's own `updated` stamp is when the METADATA
    # changed. Neither is a date the dataset was modified, so the field is left for the author.
    assert "schema:dateModified" not in lookup.datacite_to_cdif(DATACITE)


def test_datacite_publisher_as_plain_string():
    payload = {"data": {"attributes": {"doi": "10.5555/x", "publisher": "Old Style Publisher"}}}
    r = lookup.datacite_to_cdif(payload)
    assert r["schema:publisher"]["schema:name"] == "Old Style Publisher"
    assert "schema:creator" not in r and "schema:keywords" not in r  # nothing empty is returned


def test_crossref_maps_authors_and_date():
    payload = {
        "message": {
            "DOI": "10.5555/ABC",
            "title": ["A paper"],
            "author": [
                {"given": "G.", "family": "Kay", "ORCID": "http://orcid.org/0000-0002-1825-0097", "affiliation": [{"name": "Lab"}]},
                {"name": "The Consortium", "affiliation": []},
            ],
            "publisher": "A Publisher",
            "issued": {"date-parts": [[2013, 7, 31]]},
            "license": [{"URL": "https://example.org/licence"}],
            "URL": "https://doi.org/10.5555/abc",
        }
    }
    r = lookup.crossref_to_cdif(payload)
    assert r["schema:identifier"] == "https://doi.org/10.5555/abc"
    assert r["schema:datePublished"] == "2013-07-31"
    assert r["schema:creator"]["@list"] == [
        {
            "@type": "schema:Person",
            "schema:name": "G. Kay",
            "schema:identifier": "https://orcid.org/0000-0002-1825-0097",
            "schema:affiliation": {"schema:name": "Lab"},
        },
        {"@type": "schema:Organization", "schema:name": "The Consortium"},
    ]


def test_crossref_year_only_gives_no_date():
    payload = {"message": {"DOI": "10.5555/y", "issued": {"date-parts": [[2013]]}}}
    assert "schema:datePublished" not in lookup.crossref_to_cdif(payload)


def test_ror_uses_the_display_name():
    payload = {
        "items": [
            {
                "id": "https://ror.org/035a68863",
                "names": [
                    {"types": ["alias"], "value": "Geological Survey"},
                    {"types": ["acronym"], "value": "USGS"},
                    {"types": ["ror_display", "label"], "value": "United States Geological Survey"},
                ],
                "locations": [{"geonames_details": {"country_name": "United States"}}],
            },
            {"id": "https://ror.org/none", "names": [{"types": ["alias"], "value": "No display name"}]},
        ]
    }
    assert lookup.ror_to_organisations(payload) == [
        {
            "name": "United States Geological Survey",
            "identifier": "https://ror.org/035a68863",
            "acronym": "USGS",
            "country": "United States",
        }
    ]


def test_orcid_people_and_missing_names():
    payload = {
        "expanded-result": [
            {"orcid-id": "0000-0002-1825-0097", "given-names": "Josiah", "family-names": "Carberry", "credit-name": None, "institution-name": ["Brown University"]},
            {"orcid-id": "0000-0000-0000-0000", "given-names": None, "family-names": None, "credit-name": None, "institution-name": []},
        ]
    }
    assert lookup.orcid_to_people(payload) == [
        {"name": "Josiah Carberry", "identifier": "https://orcid.org/0000-0002-1825-0097", "affiliations": ["Brown University"]}
    ]
    assert lookup.orcid_to_people({"expanded-result": None}) == []  # what ORCID sends for no hits


def test_orcid_query_prefers_an_id_and_escapes_nothing_dangerous():
    assert lookup.orcid_query("https://orcid.org/0000-0002-1825-0097") == "orcid:0000-0002-1825-0097"
    q = lookup.orcid_query("josiah carberry")
    assert q.count(" AND ") == 1 and "family-name:carberry*" in q
    assert "family-names:" not in q  # the plural is a result field; as a search field ORCID answers 500
    # punctuation that means something in the search syntax never reaches the query
    assert lookup.orcid_query('carberry") OR (x:*') .count("carberry") == 3
    with pytest.raises(HTTPException):
        lookup.orcid_query("123 !!")


@pytest.mark.parametrize(
    "text",
    ["10.5555/Example-1", "doi:10.5555/example-1", "https://doi.org/10.5555/example-1", " 10.5555/example-1. "],
)
def test_doi_is_normalised(text):
    assert lookup.normalise_doi(text) == "10.5555/example-1"


def test_not_a_doi_is_rejected():
    with pytest.raises(HTTPException) as e:
        lookup.normalise_doi("zenodo 1234")
    assert e.value.status_code == 422
