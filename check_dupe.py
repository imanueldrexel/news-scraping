import redis
import hashlib
import sys

def check_url(url, redis_host='localhost', redis_port=6379):
    # Connect to Redis
    try:
        r = redis.Redis(host=redis_host, port=redis_port, decode_responses=True)
        r.ping()
    except redis.ConnectionError:
        print(f"Error: Could not connect to Redis at {redis_host}:{redis_port}")
        return

    # Calculate MD5 hash of the URL
    url_hash = hashlib.md5(url.encode()).hexdigest()
    key = f"dedup:url:{url_hash}"

    # Check existence
    if r.exists(key):
        ttl = r.ttl(key)
        saved_url = r.get(key)
        print(f"\n[FOUND] URL is marked as duplicate.")
        print(f"Key: {key}")
        print(f"TTL: {ttl} seconds remaining")
        print(f"Stored Value: {saved_url}")
    else:
        print(f"\n[NOT FOUND] URL is NOT in the deduplication cache.")
        print(f"Key checked: {key}")
        print("This URL would be processed if scraped now.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python check_dupe.py <url>")
        print("Example: python check_dupe.py https://www.example.com/news/article-1")
        sys.exit(1)
    
    url = sys.argv[1]
    check_url(url)
