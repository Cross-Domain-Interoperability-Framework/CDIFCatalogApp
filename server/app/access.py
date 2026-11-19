"""Who may see and change a record, decided by labels.

Every record carries labels and every user carries labels. A user may see a record when the two
sets share a label, so the same test works in SQL (`labels && %s`) and in Python. The scheme is
the one CKAN uses for its dataset permission labels.

Sign-in is not built yet, so every request is anonymous and holds only the `public` label. The
functions here are what sign-in will plug into.
"""
from dataclasses import dataclass

PUBLIC = "public"
HARVEST_EDIT = "harvest-edit"  # edit harvested records of one's own organisations
HARVEST_EDIT_ALL = "harvest-edit-all"  # the catalog-wide version, for central staff


@dataclass(frozen=True)
class User:
    id: str | None = None
    organisations: tuple = ()
    permissions: frozenset = frozenset()


ANONYMOUS = User()


def current_user() -> User:
    """The user making the request. Anonymous until sign-in exists."""
    return ANONYMOUS


def record_labels(status: str, organisation: str | None = None, creator: str | None = None) -> list[str]:
    """Labels for a record. Only a published record is public; an unpublished one stays visible
    to its organisation's members and to whoever created it."""
    labels = [PUBLIC] if status == "published" else []
    if organisation:
        labels.append(f"member-{organisation}")
    if creator:
        labels.append(f"creator-{creator}")
    return labels


def user_labels(user: User) -> list[str]:
    labels = [PUBLIC]
    if user.id:
        labels.append(f"creator-{user.id}")
    labels += [f"member-{org}" for org in user.organisations]
    return labels


def can_see(user: User, labels: list[str]) -> bool:
    return bool(set(user_labels(user)) & set(labels))


def can_edit_harvested(user: User, organisation: str | None) -> bool:
    """A data manager may edit harvested records only from sources their own organisation owns."""
    if HARVEST_EDIT_ALL in user.permissions:
        return True
    return HARVEST_EDIT in user.permissions and organisation is not None and organisation in user.organisations
