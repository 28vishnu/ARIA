import time
import functools

def timed_stage(stage_name: str):
    """Decorator to measure and log execution timing for performance tuning."""
    def decorator(func):
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                res = await func(*args, **kwargs)
                elapsed = (time.perf_counter() - start) * 1000
                print(f"[{stage_name}] ............ {elapsed:.1f} ms")
                return res
            except Exception as e:
                elapsed = (time.perf_counter() - start) * 1000
                print(f"[{stage_name} ERROR] ({elapsed:.1f} ms): {e}")
                raise e
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                res = func(*args, **kwargs)
                elapsed = (time.perf_counter() - start) * 1000
                print(f"[{stage_name}] ............ {elapsed:.1f} ms")
                return res
            except Exception as e:
                elapsed = (time.perf_counter() - start) * 1000
                print(f"[{stage_name} ERROR] ({elapsed:.1f} ms): {e}")
                raise e
        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
    return decorator
  
