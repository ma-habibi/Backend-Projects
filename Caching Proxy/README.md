# Caching Proxy
a caching server that caches responses from other serversA

A solution to the project at https://roadmap.sh/projects/caching-server

## HOW TO RUN

By running:

```sh
python main.py --port 3000 --origin http://dummyjson.com/users
```
The caching proxy server should start on port 3000 and forward requests to http://dummyjson.com/users and add the headers to the response that indicate whether the response is from the cache or the server.

```json
# If the response is from the cache
X-Cache: HIT

# If the response is from the origin server
X-Cache: MISS
```

Clear the cache by running a command like following:

```sh
python main.py --clear-cache
```

**_Note:_** The main just prints response.