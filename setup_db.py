import os
from db import get_db_connection

def create_database():
    import mysql.connector
    from mysql.connector import Error
    
    host = os.environ.get('DB_HOST', 'localhost')
    user = os.environ.get('DB_USER', 'root')
    passwords = [os.environ.get('DB_PASSWORD', 'Arnavganu@007'), '']
    
    for pwd in passwords:
        try:
            conn = mysql.connector.connect(
                host=host,
                user=user,
                password=pwd
            )
            if conn.is_connected():
                cursor = conn.cursor()
                cursor.execute("CREATE DATABASE IF NOT EXISTS canteen_db")
                print("Database 'canteen_db' created or already exists.")
                cursor.close()
                conn.close()
                return True
        except Error as e:
            continue
    print("Error connecting to MySQL Server.")
    return False

def run_schema():
    try:
        conn = get_db_connection()
        if conn and conn.is_connected():
            cursor = conn.cursor()
            base_dir = os.path.dirname(os.path.abspath(__file__))
            schema_path = os.path.join(base_dir, 'schema.sql')
            if not os.path.exists(schema_path):
                schema_path = os.path.join(base_dir, 'canteen_app', 'schema.sql')

            with open(schema_path, 'r') as f:
                schema = f.read()

            statements = schema.split(';')
            for statement in statements:
                if statement.strip():
                    cursor.execute(statement)
            
            print("Schema executed successfully.")
            conn.commit()
            cursor.close()
            conn.close()
            return True
    except Exception as e:
        print(f"Error executing schema: {e}")
        return False

if __name__ == "__main__":
    if create_database():
        run_schema()
