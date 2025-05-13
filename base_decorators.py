# -*- coding: utf-8 -*-
"""
Time    : 2025/5/10 11:27
Author  : jiaqi.wang
"""
import time
from datetime import datetime, timedelta
from functools import wraps
from typing import Callable, TypeVar, Optional, Type, Any, Union
import signal
from contextlib import contextmanager

T = TypeVar('T')
Predicate = Callable[..., bool]


@contextmanager
def timeout_context(timeout: float):
    """Context manager for timeout control using signals"""

    def raise_timeout(signum, frame):
        raise TimeoutError("Operation timed out")

    signal.signal(signal.SIGALRM, raise_timeout)
    signal.alarm(int(timeout))
    try:
        yield
    finally:
        signal.alarm(0)


def ctrl_c_decorator(func: Callable[..., T]) -> Callable[..., T]:
    """Decorator to send Ctrl+C (0x03) after function execution"""

    @wraps(func)
    def wrapper(self: Any, *args: Any, **kwargs: Any) -> T:
        try:
            return func(self, *args, **kwargs)
        finally:
            try:
                self.write(chr(0x03))
            except Exception as e:
                print(f"Failed to send Ctrl+C: {e}")

    return wrapper


def func_timeout(
        timeout: Union[int, float] = 10,
        delay: Union[int, float] = 0.5,
        raise_exception: bool = True
) -> Callable[[Callable[..., T]], Callable[..., Optional[T]]]:
    """
    Decorator to retry function until timeout or success
    Args:
        timeout: Total timeout in seconds
        delay: Delay between retries in seconds
        raise_exception: Whether to raise exception on timeout
    """

    def decorator(func: Callable[..., T]) -> Callable[..., Optional[T]]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Optional[T]:
            end_time = datetime.now() + timedelta(seconds=timeout)
            while datetime.now() < end_time:
                result = func(*args, **kwargs)
                if result:
                    return result
                time.sleep(delay)
            if raise_exception:
                raise TimeoutError(f"Function {func.__name__} timed out after {timeout} seconds")
            return None

        return wrapper

    return decorator


def wait_for(
        predicate: Predicate,
        timeout: Union[int, float] = 1.0,
        interval: Union[int, float] = 0.2,
        error_type: str = None,
        **kwargs: Any
) -> bool:
    """
    Wait until predicate returns True or timeout occurs
    Args:
        predicate: Callable that returns a boolean
        timeout: Maximum wait time in seconds
        interval: Check interval in seconds
        error_type: Exception type to raise on timeout (None to return False)
        kwargs: Arguments to pass to predicate
    Returns:
        bool: True if predicate returned True, False or raises exception on timeout
    """
    timeout = float(timeout)
    cur = datetime.now()
    while (datetime.now() - cur).total_seconds() <= timeout:
        if predicate(**kwargs):
            return True
        time.sleep(interval)

    if error_type == 'strict':
        raise TimeoutError(f"Predicate {predicate.__name__} timed out after {timeout} seconds")
    return False


# Example usage
# if __name__ == "__main__":
#     # Example predicate function
#     def is_ready(status: str) -> bool:
#         return status == "ready"
#
#
#     # Using wait_for with different options
#     print("Test 1 (success):", wait_for(is_ready, timeout=2, interval=0.1, status="ready"))
#     print("Test 2 (timeout):", wait_for(is_ready, timeout=1, interval=0.1, status="busy"))
#
#     try:
#         wait_for(is_ready, timeout=1, interval=0.1,
#                  exception=TimeoutError, status="busy")
#     except TimeoutError as e:
#         print("Test 3 (exception):", e)
#
#
#     # Using func_timeout decorator
#     @func_timeout(timeout=3, delay=0.5)
#     def check_connection():
#         return False  # Simulate failure
#
#
#     try:
#         check_connection()
#     except TimeoutError as e:
#         print("Test 4 (decorator):", e)
