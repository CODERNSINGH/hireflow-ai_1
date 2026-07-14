from sqlalchemy.orm import declarative_base

# Shared declarative base for all models so Alembic autogenerate
# can see a single metadata object containing every table.
Base = declarative_base()
