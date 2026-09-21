"""Seed roles and permissions."""

from __future__ import annotations

import asyncio

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.user import Permission, Role, role_permissions

PERMISSIONS = [
    ("ai.generate", "Generate AI content"),
    ("ai.stream", "Stream AI content"),
    ("ai.jobs.create", "Create AI jobs"),
    ("ai.jobs.read", "Read AI jobs"),
    ("files.upload", "Upload files"),
    ("files.read", "Read files"),
    ("users.manage", "Manage users"),
]

ROLES = {
    "admin": [p[0] for p in PERMISSIONS],
    "user": [
        "ai.generate",
        "ai.stream",
        "ai.jobs.create",
        "ai.jobs.read",
        "files.upload",
        "files.read",
    ],
    "developer": [
        "ai.generate",
        "ai.stream",
        "ai.jobs.create",
        "ai.jobs.read",
        "files.upload",
        "files.read",
    ],
    "service": ["ai.generate", "ai.jobs.create", "ai.jobs.read", "files.upload"],
}


async def seed(session: AsyncSession) -> None:
    perm_map: dict[str, Permission] = {}
    for name, description in PERMISSIONS:
        existing = (
            await session.execute(select(Permission).where(Permission.name == name))
        ).scalar_one_or_none()
        if existing:
            perm_map[name] = existing
            continue
        permission = Permission(name=name, description=description)
        session.add(permission)
        await session.flush()
        perm_map[name] = permission

    for role_name, perm_names in ROLES.items():
        role = (
            await session.execute(select(Role).where(Role.name == role_name))
        ).scalar_one_or_none()
        if not role:
            role = Role(name=role_name, description=f"{role_name} role")
            session.add(role)
            await session.flush()

        await session.execute(delete(role_permissions).where(role_permissions.c.role_id == role.id))
        rows = [
            {"role_id": role.id, "permission_id": perm_map[name].id}
            for name in perm_names
            if name in perm_map
        ]
        if rows:
            await session.execute(role_permissions.insert(), rows)

    await session.flush()


async def main() -> None:
    async with AsyncSessionLocal() as session:
        await seed(session)
        await session.commit()
    print("Seed completed")


if __name__ == "__main__":
    asyncio.run(main())
