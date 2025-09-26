import sqlite3
import json
import os

# Define the path to the database and JSON file
base_dir = os.path.dirname(os.path.abspath(__file__))
db_path = os.path.join(base_dir, 'jmdict.db')
json_path = os.path.join(base_dir, 'kanji_jlpt.json')

def create_and_populate_kanji_table():
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Drop the old table if it exists and create a new one with the new columns
        cursor.execute("DROP TABLE IF EXISTS kanji_jlpt")
        cursor.execute("""
            CREATE TABLE kanji_jlpt (
                kanji TEXT PRIMARY KEY,
                jlpt_level INTEGER,
                freq_mainichi_shinbun INTEGER,
                grade INTEGER
            )
        """)
        
        # Read the JSON data
        with open(json_path, 'r', encoding='utf-8') as f:
            kanji_data = json.load(f)

        # Insert data into the new table
        for kanji, details in kanji_data.items():
            if 'jlpt' in details:  # Ensure the kanji has JLPT data
                cursor.execute("""
                    INSERT INTO kanji_jlpt (kanji, jlpt_level, freq_mainichi_shinbun, grade)
                    VALUES (?, ?, ?, ?)
                """, (kanji, details.get('jlpt'), details.get('freq_mainichi_shinbun'), details.get('grade')))

        conn.commit()
        print("kanji_jlpt table created and populated successfully.")

    except FileNotFoundError:
        print(f"Error: Required file not found. Make sure {json_path} exists.")
    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        if conn:
            conn.close()

if __name__ == '__main__':
    create_and_populate_kanji_table()