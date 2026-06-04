from cachetools import TTLCache

# In-memory caching for smaller applications
# Caches up to 1000 items with a Time-To-Live (TTL) of 300 seconds (5 minutes)
# Great for caching database lookup results like course lists or stats
api_cache = TTLCache(maxsize=1000, ttl=300)

def get_cached_or_compute(key: str, compute_func):
    """
    Fetches a value from the cache by key. 
    If not found, runs compute_func() to generate it, stores it, and returns it.
    """
    if key in api_cache:
        return api_cache[key]
    
    result = compute_func()
    api_cache[key] = result
    return result

def invalidate_cache(key_prefix: str):
    """
    Invalidates all cache keys that start with the given prefix.
    Useful for clearing course lists when a new course is added.
    """
    keys_to_delete = [k for k in api_cache.keys() if k.startswith(key_prefix)]
    for k in keys_to_delete:
        del api_cache[k]
