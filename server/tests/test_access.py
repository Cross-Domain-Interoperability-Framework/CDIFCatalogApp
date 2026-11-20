"""Labels: who may see a record, and who may edit a harvested one."""
from app.access import (
    ANONYMOUS, HARVEST_EDIT, HARVEST_EDIT_ALL, User, can_edit_harvested, can_see, record_labels, user_labels,
)


def test_only_a_published_record_is_public():
    assert "public" in record_labels("published", "org-a")
    assert "public" not in record_labels("invalid", "org-a")
    assert "public" not in record_labels("withdrawn", "org-a")


def test_an_unpublished_record_is_seen_by_its_organisation_and_creator_only():
    labels = record_labels("invalid", organisation="org-a", creator="u1")
    assert not can_see(ANONYMOUS, labels)
    assert can_see(User(id="u2", organisations=("org-a",)), labels)
    assert can_see(User(id="u1"), labels)
    assert not can_see(User(id="u2", organisations=("org-b",)), labels)


def test_anonymous_holds_only_the_public_label():
    assert user_labels(ANONYMOUS) == ["public"]


def test_harvest_edit_is_scoped_to_the_users_own_organisations():
    manager = User(id="u1", organisations=("org-a",), permissions=frozenset({HARVEST_EDIT}))
    assert can_edit_harvested(manager, "org-a")
    assert not can_edit_harvested(manager, "org-b")
    assert not can_edit_harvested(manager, None)
    # membership without the permission is not enough
    assert not can_edit_harvested(User(id="u2", organisations=("org-a",)), "org-a")


def test_the_catalog_wide_permission_covers_every_organisation():
    central = User(id="u3", permissions=frozenset({HARVEST_EDIT_ALL}))
    assert can_edit_harvested(central, "org-b") and can_edit_harvested(central, None)
