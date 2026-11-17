"""Import every model module here so ``Base.metadata`` is complete for Alembic.

No models exist yet; identity and tenancy tables arrive in Phase 1.
"""

from officemates.db.base import Base

__all__ = ["Base"]
