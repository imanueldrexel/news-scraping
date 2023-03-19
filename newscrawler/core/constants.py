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
TW_API_KEY = "jB0mMFIbHCBwTxXvZtshxLjLP"
TW_API_SECRET_KEY = "bpGR5DDzujnoza0toO9lZxnzRjKosb6ZR8LqlJHigTZRbFtEAm"
TW_BEARER_TOKEN = "AAAAAAAAAAAAAAAAAAAAAOPemAEAAAAAgKlHyS1V%2Faz32XXtZE3Fnj4lsrc%3DhrxTupTzwxgxEiH8hQYmNPchIbPpvfWZ0ldo2I7mg1R7euF1QV"