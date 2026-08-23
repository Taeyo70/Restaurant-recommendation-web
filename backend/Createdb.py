import pandas as pd
import sqlite3
import os

# Path to the Excel file
excel_file = os.path.join("..", "data", "C:\Users\shrad\Downloads\restaurants_final_with_maps.xlsx")

# Read Excel
df = pd.read_excel(excel_file)

# Create SQLite database
conn = sqlite3.connect("restaurants.db")

# Write data to a table named 'restaurants'
df.to_sql("restaurants", conn, if_exists="replace", index=False)

# Close connection
conn.close()

print("Database created successfully!")
