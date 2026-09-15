"""
Run once before Phase 1 goes live to delete the old single-index FAISS store.
NEWS_L1 and NEWS_L2 will be created automatically on the first crawl run.

Usage:
    python scripts/reset_faiss_index.py
"""
import os
import shutil

OLD_INDEXES = [
    os.getenv("VECTOR_DB_NAME", "NEWS_DEEPSEEK_8B"),
]

for name in OLD_INDEXES:
    if os.path.exists(name):
        shutil.rmtree(name)
        print(f"Deleted: {name}")
    else:
        print(f"Not found (skipping): {name}")

print("\nDone. NEWS_L1 and NEWS_L2 will be created on the first crawl run.")
