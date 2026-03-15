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
        
    # Recent Files Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS RecentFiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path TEXT UNIQUE,
            last_opened DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()

# Helper functions for Recent Files
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

def get_item_details(search_name):
    """
    Searches all material/fixture tables for an item by name and returns its details.
    """
    if not search_name:
        return {}
        
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # The list of all your material/item tables
    tables = [
        "Floors", "Walls", "Doors", "Windows", "Fixtures", 
        "Electrical Appliances", "Closet", "Toilet", "Sink", 
        "Sauna Bench", "Fire Place", "Bathtub", "Chimney"
    ]
    
    # Use LIKE for a flexible, case-insensitive search
    search_pattern = f"%{search_name.strip()}%"
    
    for table in tables:
        try:
            cursor.execute(f'''
                SELECT item_no, unit, markup_percentage, cost, brand_name 
                FROM "{table}" 
                WHERE item_name LIKE ? OR brand_name LIKE ?
                LIMIT 1
            ''', (search_pattern, search_pattern))
            
            row = cursor.fetchone()
            if row:
                conn.close()
                return {
                    'Item_No': row[0] if row[0] else "",
                    'Unit': row[1] if row[1] else "",
                    'Markup_Percentage': row[2] if row[2] else 0.0,
                    'Cost_per_Unit': row[3] if row[3] else 0.0,
                    'Brand_Name': row[4] if row[4] else ""  # NEW FIELD
                }
        except sqlite3.OperationalError:
            continue
            
    conn.close()
    return {}

if __name__ == "__main__":
    init_db()
    print("Database initialized successfully.")