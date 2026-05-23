import os
import pg8000
from dotenv import load_dotenv

load_dotenv()

db_url = os.getenv("DATABASE_URL")
print("DB URL:", db_url)

# Extract params
# URL format: postgresql://postgres:voice-clinical-agent@db.sxppmzsgrejsvokfefvu.supabase.co:5432/postgres
# let's try direct pg8000 connection
try:
    print("Connecting with standard pg8000...")
    conn = pg8000.connect(
        user="postgres",
        password="voice-clinical-agent",
        host="db.sxppmzsgrejsvokfefvu.supabase.co",
        port=5432,
        database="postgres"
    )
    print("Success standard!")
    conn.close()
except Exception as e:
    print("Failed standard pg8000:", e)

try:
    print("Connecting with pg8000 + SSL required...")
    import ssl
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE
    
    conn = pg8000.connect(
        user="postgres",
        password="voice-clinical-agent",
        host="db.sxppmzsgrejsvokfefvu.supabase.co",
        port=5432,
        database="postgres",
        ssl_context=ssl_context
    )
    print("Success with SSL!")
    conn.close()
except Exception as e:
    print("Failed SSL pg8000:", e)
