"""Who may see and change a record, decided by labels.

Every record carries labels and every user carries labels. A user may see a record when the two
sets share a label, so the same test works in SQL (`labels && %s`) and in Python. The scheme is
the one CKAN uses for its dataset permission labels.

What a user may do is decided by groups. A user belongs to groups, and each group carries a
fixed set of named permissions. Who the user is comes from sign-in (auth.py); a request with no
session is anonymous and holds only the `public` label and no permissions.
"""
from dataclasses import dataclass

PUBLIC = "public"
HARVEST_EDIT = "harvest-edit"  # edit harvested records of one's own organisations
HARVEST_EDIT_ALL = "harvest-edit-all"  # the catalog-wide version, for central staff
HARVEST = "harvest"  # register harvest sources, and start, stop and clear their runs

# Groups and what each may do. To start, only admins may harvest; data managers get it when
# harvest sources are scoped to organisations.
ADMINS = "admins"
GROUPS = {
    ADMINS: frozenset({HARVEST, HARVEST_EDIT_ALL}),
}


def permissions_of(groups) -> frozenset:
    """Every permission the given groups carry. A group this code does not know carries none."""
    return frozenset().union(*(GROUPS.get(g, frozenset()) for g in groups))


@dataclass(frozen=True)
class User:
    id: str | None = None
    organisations: tuple = ()
    permissions: frozenset = frozenset()
    orcid: str | None = None
    name: str | None = None
    groups: tuple = ()


ANONYMOUS = User()


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
