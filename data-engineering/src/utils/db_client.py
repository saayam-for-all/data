import os
import psycopg2

class DatabaseClient:
    """Abstraction layer for database operations.
    
    When we migrate to Redis/vector store, we only need to
    change this file, not every file that uses the DB.
    """
    def __init__(self):
        # Currently PostgreSQL
        self.conn = self._get_postgres_connection()
    
    def _get_postgres_connection(self):
        """Initializes and returns the psycopg2 database connection."""
        db_config = {
            "host": os.environ.get('host'),
            "port": os.environ.get('port'),
            "dbname": os.environ.get('dbname'),
            "user": os.environ.get('user'),
            "password": os.environ.get('password')
        }
        return psycopg2.connect(**db_config)
