"""Role-based access control and group-level isolation."""

from __future__ import annotations

from dataclasses import dataclass, field
import uuid
from typing import Iterable

ROLE_RANK = {
    "viewer": 1,
    "operator": 2,
    "editor": 3,
}

VALID_ROLES = tuple(ROLE_RANK.keys())
VALID_STATUSES = ("pending", "active", "rejected", "disabled")

# Minimum group role required for each permission.
# Platform admins bypass group role checks and have access to all permissions.
PERMISSIONS: dict[str, str | None] = {
    # Reading
    "dashboard:read": "viewer",
    "settings:read": "viewer",
    "agent:read": "viewer",
    "run:read": "viewer",
    "datasource:read": "viewer",
    "llm:read": "viewer",
    "llm_provider:read": "viewer",
    "secret_provider:read": "viewer",
    "delivery_channel:read": "viewer",
    "chat:read": "viewer",
    "chat:ask": "viewer",
    # Operating (operator+)
    "chat:delete": "operator",
    "agent:run": "operator",
    "run:trigger": "operator",
    "run:cancel": "operator",
    "run:rerun": "operator",
    "delivery:resend": "operator",
    "schedule:pause": "operator",
    "datasource:test": "operator",
    "llm:test": "operator",
    "llm_provider:test": "operator",
    "secret_provider:test": "operator",
    "delivery_channel:test": "operator",
    # Editing (editor+)
    "builder:draft": "editor",
    "agent:write": "editor",
    "agent:delete": "editor",
    "run:delete": "editor",
    "datasource:write": "editor",
    "datasource:delete": "editor",
    "llm:write": "editor",
    "llm:delete": "editor",
    "llm_provider:write": "editor",
    "llm_provider:delete": "editor",
    "secret_provider:write": "editor",
    "secret_provider:delete": "editor",
    "delivery_channel:write": "editor",
    "delivery_channel:delete": "editor",
    # Platform administration (admin only)
    "admin:users": None,
    "admin:groups": None,
    "admin:audit": None,
}


@dataclass(frozen=True)
class GroupMembershipInfo:
    group_id: uuid.UUID
    group_name: str
    role: str


@dataclass(frozen=True)
class Principal:
    user_id: uuid.UUID | None
    email: str
    display_name: str
    status: str  # active | pending | rejected | disabled
    is_admin: bool
    memberships: tuple[GroupMembershipInfo, ...] = field(default_factory=tuple)
    active_group_id: uuid.UUID | None = None
    auth_method: str = "session"  # session | bearer | disabled | system

    @property
    def actor(self) -> str:
        if self.email:
            return self.email
        if self.user_id:
            return f"user:{self.user_id}"
        return "ui"

    @property
    def group_ids(self) -> set[uuid.UUID]:
        return {m.group_id for m in self.memberships}

    def role_in(self, group_id: uuid.UUID | None) -> str | None:
        if group_id is None:
            return None
        for m in self.memberships:
            if m.group_id == group_id:
                return m.role
        return None

    @property
    def highest_role(self) -> str | None:
        best: str | None = None
        best_rank = 0
        for m in self.memberships:
            rank = ROLE_RANK.get(m.role, 0)
            if rank > best_rank:
                best_rank = rank
                best = m.role
        return best

    def effective_group_id(self, requested: uuid.UUID | None = None) -> uuid.UUID | None:
        if requested is not None:
            if self.is_admin or requested in self.group_ids:
                return requested
            return None
        if self.active_group_id and (self.is_admin or self.active_group_id in self.group_ids):
            return self.active_group_id
        if self.memberships:
            return self.memberships[0].group_id
        return None


def role_allows(user_role: str | None, required_role: str | None) -> bool:
    if required_role is None:
        return False
    if user_role is None:
        return False
    return ROLE_RANK.get(user_role, 0) >= ROLE_RANK.get(required_role, 99)


def has_permission(principal: Principal, permission: str, group_id: uuid.UUID | None = None) -> bool:
    if principal.status != "active":
        return False
    if permission not in PERMISSIONS:
        return False
    required = PERMISSIONS[permission]
    if principal.is_admin:
        return True
    if required is None:
        # Admin-only permission
        return False
    if group_id is not None:
        role = principal.role_in(group_id)
        return role_allows(role, required)
    # Check if the user has the required role in their active group (or any group if no active group is set)
    if principal.active_group_id is not None:
        role = principal.role_in(principal.active_group_id)
        if role_allows(role, required):
            return True
    return any(role_allows(m.role, required) for m in principal.memberships)


def allowed_group_ids_for(principal: Principal, permission: str) -> set[uuid.UUID] | None:
    """Return None when the principal may see all groups (platform admin), or the set of allowed group IDs."""
    if principal.status != "active":
        return set()
    if principal.is_admin:
        return None
    required = PERMISSIONS.get(permission)
    if required is None:
        return set()
    return {m.group_id for m in principal.memberships if role_allows(m.role, required)}


def can_access_record(principal: Principal, owner_group_id: uuid.UUID | None, permission: str = "agent:read") -> bool:
    """True if principal can access a record owned by owner_group_id with the given permission."""
    if principal.status != "active":
        return False
    if principal.is_admin:
        return True
    if owner_group_id is None:
        return False
    return has_permission(principal, permission, group_id=owner_group_id)


def permitted_actions(principal: Principal, group_id: uuid.UUID | None = None) -> list[str]:
    """List all permission keys granted to the principal (for UI gating)."""
    if principal.status != "active":
        return []
    return [perm for perm in PERMISSIONS if has_permission(principal, perm, group_id=group_id)]


def scope_query(query, model, principal: Principal, permission: str = "agent:read", group_id: uuid.UUID | None = None):
    """Filter a SQLAlchemy query on model.owner_group_id according to principal's group memberships."""
    allowed = allowed_group_ids_for(principal, permission)
    if allowed is None:
        # Platform admin sees all groups (or filters to requested group_id if explicitly specified)
        if group_id is not None:
            return query.filter(model.owner_group_id == group_id)
        return query
    if group_id is not None:
        if group_id not in allowed:
            return query.filter(False)
        return query.filter(model.owner_group_id == group_id)
    if not allowed:
        return query.filter(False)
    return query.filter(model.owner_group_id.in_(list(allowed)))
