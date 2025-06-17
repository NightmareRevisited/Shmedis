from .core import Shmedis

try:
    from multiprocessing import resource_tracker
except ImportError:
    from shared_memory import resource_tracker


def disable_shm_tracking():
    """
    In python3.13- ,shared memory is released before the process exits.
    This function is used to disable resource tracker for shared memory.
    """
    original_register = resource_tracker.register

    def patched_register(name, rtype):
        if rtype == "shared_memory":
            return
        return original_register(name, rtype)

    resource_tracker.register = patched_register


disable_shm_tracking()

__all__ = ["Shmedis"]
