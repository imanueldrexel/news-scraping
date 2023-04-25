import os


S3_BUCKET = os.getenv("S3_BUCKET")
REGION = os.getenv("REGION", "ap-southeast-1")
VERBOSE = os.getenv("VERBOSE", "False") == "True"
PARALLELIZE = os.getenv("PARALLELIZE", "False") == "True"
REQUEST_MAX_RETRIES = int(os.getenv("REQUEST_MAX_RETRIES", 5))
EXECUTABLE_PATH = os.getenv(
    "EXECUTABLE_PATH", "/Users/imanuel/Downloads/chromedriver_2"
)
MAX_WORKER = os.getenv("MAX_WORKER")
if MAX_WORKER:
    MAX_WORKER = int(MAX_WORKER)
TW_API_KEY = os.getenv("TW_API_KEY")
TW_API_SECRET_KEY = os.getenv("TW_API_SECRET_KEY")
TW_BEARER_TOKEN = os.getenv("TW_BEARER_TOKEN")


OPENAI_KEY = os.getenv("OPENAI_KEY")
OPEN_AI_MODEL = os.getenv("OPEN_AI_MODEL")