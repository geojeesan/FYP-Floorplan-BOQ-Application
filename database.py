import sqlite3
import os

DB_NAME = "boq_materials.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    tables = [
        "Floors", "Walls", "Doors", "Windows", "Fixtures", 
        "Electrical Appliances", "Closet", "Toilet", "Sink", 
        "Sauna Bench", "Fire Place", "Bathtub", "Chimney"
    ]
    
    for table in tables:
        cursor.execute(f'''
            CREATE TABLE IF NOT EXISTS "{table}" (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_no TEXT,
                item_name TEXT,
                brand_name TEXT,
                image BLOB,
                texture_for_3d BLOB,
                cost REAL,
                unit TEXT,
                markup_percentage REAL
            )
        ''')
        
    # --- NEW: Recent Files Table ---
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS RecentFiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path TEXT UNIQUE,
            last_opened DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()

# --- NEW: Helper functions for Recent Files ---
def add_recent_file(file_path):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    # INSERT OR REPLACE updates the timestamp if the file is already in the list
    cursor.execute('''
        INSERT OR REPLACE INTO RecentFiles (file_path, last_opened) 
        VALUES (?, CURRENT_TIMESTAMP)
    ''', (file_path,))
    conn.commit()
    conn.close()

def get_recent_files(limit=10):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    # Fetch the most recently opened files up to the limit
    cursor.execute('SELECT id, file_path FROM RecentFiles ORDER BY last_opened DESC LIMIT ?', (limit,))
    rows = cursor.fetchall()
    conn.close()
    return rows

def delete_recent_file(file_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM RecentFiles WHERE id = ?', (file_id,))
    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
    print("Database initialized successfully.")