import os
import mysql.connector
from mysql.connector import Error

def get_db_connection():
    """Connects to the MySQL database."""
    host = os.environ.get('DB_HOST', 'localhost')
    user = os.environ.get('DB_USER', 'root')
    database = os.environ.get('DB_NAME', 'canteen_db')
    
    # Try specified password or defaults
    passwords_to_try = []
    if 'DB_PASSWORD' in os.environ:
        passwords_to_try.append(os.environ['DB_PASSWORD'])
    else:
        passwords_to_try = ['Arnavganu@007', '']

    last_error = None
    for pwd in passwords_to_try:
        try:
            connection = mysql.connector.connect(
                host=host,
                user=user,
                password=pwd,
                database=database
            )
            if connection.is_connected():
                return connection
        except Error as e:
            last_error = e

    print(f"Error while connecting to MySQL: {last_error}")
    return None

