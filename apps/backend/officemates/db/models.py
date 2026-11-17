"""Import every model module here so ``Base.metadata`` is complete for Alembic and tests."""

from officemates.audit import models as audit_models
from officemates.db.base import Base
from officemates.identity import models as identity_models

__all__ = ["Base", "audit_models", "identity_models"]
