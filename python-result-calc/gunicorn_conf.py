import os

# Gunicorn configuration module. Values may be overridden via environment variables.

def _int_env(name, default):
    try:
        return int(os.environ.get(name, default))
    except Exception:
        return default

def _str_env(name, default):
    return os.environ.get(name, default)

# Worker/process settings
workers = _int_env('GUNICORN_WORKERS', 2)
threads = _int_env('GUNICORN_THREADS', 4)
worker_class = _str_env('GUNICORN_WORKER_CLASS', 'gthread')

# Timeout settings (seconds)
timeout = _int_env('GUNICORN_TIMEOUT', 120)
graceful_timeout = _int_env('GUNICORN_GRACEFUL_TIMEOUT', 30)

# Logging (inherit from environment or reasonable defaults)
loglevel = _str_env('GUNICORN_LOGLEVEL', 'info')

# Bind address is provided on the gunicorn CLI; this file mainly exposes tuning params.

def post_fork(server, worker):
    """Called just after a worker has been forked."""
    try:
        # Import here to avoid circular imports at config parse time.
        import result_calc
        server.log.info("Initializing warmup DB and starting warmup thread in worker")
        try:
            result_calc.init_warmup_db()
        except Exception:
            server.log.warning("init_warmup_db failed in post_fork")
        try:
            result_calc.start_warmup_thread()
        except Exception:
            server.log.warning("start_warmup_thread failed in post_fork")
    except Exception as e:
        server.log.warning(f"Could not start warmup in worker: {e}")
