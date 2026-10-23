from datetime import timedelta

# Timeouts
AIOHTTP_TIMEOUT_SECONDS = 600  # 10 minutes
REQUEST_TIMEOUT = 1 * 60  # 1 minute

# update queue interval in seconds
UPDATE_QUEUE_INTERVAL = 0.1


def controller_events_key(server_args) -> str:
    """Redis list where GPU schedulers tell the global controller about models they lost (dicts with
    event="model_lost", model_name, gpu_id, reason)."""
    return f"{server_args.engine_to_gpu_scheduler_key_prefix}:controller_events"
