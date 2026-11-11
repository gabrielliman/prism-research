from datetime import timedelta

# Timeouts
AIOHTTP_TIMEOUT_SECONDS = 600  # 10 minutes
REQUEST_TIMEOUT = 1 * 60  # 1 minute

# update queue interval in seconds
UPDATE_QUEUE_INTERVAL = 0.1


# s a controller instance may stay ACTIVATING/DEACTIVATING without the GPU scheduler's event (same bound as the
# policy's pending activations). Then nothing is assumed (D59): an activation is cleaned up with a deactivation,
# a deactivation stays DEACTIVATING (not serving)
LIFECYCLE_TIMEOUT_S = 120.0


def controller_events_key(server_args) -> str:
    """Redis list where GPU schedulers send the global controller dicts with model_name, gpu_id, rid (the command
    the event answers, D59) and event = "model_activated" | "model_deactivated" (success, reason) | "model_lost"
    (reason), or event="model_service_lost"."""
    return f"{server_args.engine_to_gpu_scheduler_key_prefix}:controller_events"
