import os


S3_BUCKET = os.getenv("S3_BUCKET")
REGION = os.getenv("REGION", "ap-southeast-1")
VERBOSE = os.getenv("VERBOSE", "False") == "True"
PARALLELIZE = os.getenv("PARALLELIZE", "False") == "True"
REQUEST_MAX_RETRIES = int(os.getenv("REQUEST_MAX_RETRIES", 5))
EXECUTABLE_PATH = os.getenv("EXECUTABLE_PATH", "/usr/local/bin/chromedriver")
MAX_WORKER = os.getenv("MAX_WORKER")
if MAX_WORKER:
    MAX_WORKER = int(MAX_WORKER)
