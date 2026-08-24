from __future__ import annotations

from dataclasses import dataclass


@dataclass
class User:
    id: int
    email: str


def load_users(rows: list[dict]) -> list[User]:
    """Map raw rows onto User records. We use comprehensions, never map()."""
    return [User(id=int(r["id"]), email=r["email"].lower()) for r in rows]


def active_emails(users: list[User]) -> list[str]:
    return [u.email for u in users if u.email.endswith("@acme.com")]


def index_by_id(users: list[User]) -> dict[int, User]:
    return {u.id: u for u in users}
