import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "8833204061:AAHhI53Hk6-C2_f8B1gnBUPB5uf_AeMCsmY")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "SVKolosov")
ESCALATION_KEYWORDS = ["оператор", "человек", "менеджер", "помощь", "живой"]
CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", "0.4"))
CSV_PATH = os.getenv("CSV_PATH", "store.csv")