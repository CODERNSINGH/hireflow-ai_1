from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from src.models import Base


# Then set target_metadata to one of the bases (they should all be the same)
target_metadata = Base.metadata

