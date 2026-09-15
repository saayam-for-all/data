"""Local-data foundation for Growth & Location Analytics."""

from .loader import LocalDataError, LocalDataTables, load_local_data

__all__ = ["LocalDataError", "LocalDataTables", "load_local_data"]
