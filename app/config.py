import logging
import os

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

GEMINI_TEXT_MODEL = "gemini-2.5-pro"
GEMINI_IMAGE_MODEL = "gemini-2.5-flash-image"

MONGODB_URI = os.environ["MONGO_DB_URL"]
MONGODB_DB_NAME = "content-generator"

GCS_BUCKET_NAME = os.environ["GCS_BUCKET_NAME"]
GCS_CREDENTIALS_PATH = os.environ.get("GCS_CREDENTIALS_PATH", "auto-qa-svc-key.json")
