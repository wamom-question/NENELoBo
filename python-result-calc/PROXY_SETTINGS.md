**Proxy / Load Balancer Timeout Recommendations**

- **Purpose:** HTTP clients may upload images or wait for CPU-bound OCR processing; defaults on many proxies (including Cloudflare) may close connections early. Increase proxy timeouts to avoid mid-request disconnects.

- **Recommended Nginx snippet:** see `nginx_proxy.conf` in this folder. Key values set here:
  - `proxy_connect_timeout 600s;`
  - `proxy_send_timeout 3600s;`
  - `proxy_read_timeout 3600s;`
  - `send_timeout 3600s;`
  - `client_max_body_size 20M;`

- **Cloudflare note:** Cloudflare's HTTP proxy has a hard 100s request timeout for HTTP requests (for free and most plans). If your requests require more than 100 seconds you should:
  - Use Cloudflare Workers or Argo Tunnel, or
  - Bypass Cloudflare (use DNS-only) for this API host, or
  - Break the API into async job acceptance (enqueue a job, return 202, poll for results) to avoid long HTTP requests.

- **AWS/ALB / GCP / Azure Load Balancers:** increase idle connection and request timeout values in the respective load balancer settings (set to 600s or more if needed).

- **Gunicorn settings (container):** use environment variables to tune concurrency and timeouts:
  - `GUNICORN_WORKERS` (default `2`) — process count
  - `GUNICORN_THREADS` (default `4`) — threads per worker when using `gthread`
  - `GUNICORN_TIMEOUT` (default `120`) — worker timeout in seconds

- **How to run with different settings:** Example Docker run overriding environment vars:

  `docker run -e GUNICORN_WORKERS=4 -e GUNICORN_THREADS=8 -e GUNICORN_TIMEOUT=300 -p 53744:53744 <image>`

Or with docker-compose environment section.
