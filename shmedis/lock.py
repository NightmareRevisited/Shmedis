import ctypes
import ctypes.util


class PthreadRwlockAttr(ctypes.Structure):
    pass


class PthreadRwlock(ctypes.Structure):
    _fields_ = [("data", ctypes.c_byte * 64)]  # Using a safe buffer size


PthreadRwlockAttr_p = ctypes.POINTER(PthreadRwlockAttr)
PthreadRwlock_p = ctypes.POINTER(PthreadRwlock)

libpthread_path = ctypes.util.find_library("pthread")
if not libpthread_path:
    raise OSError("pthread library not found")
libpthread = ctypes.CDLL(libpthread_path)

PTHREAD_PROCESS_SHARED = 1


class _Lock:
    def __init__(self, lock_ptr):
        self.lock_ptr = lock_ptr

    def __exit__(self, exc_type, exc_val, exc_tb):
        if libpthread.pthread_rwlock_unlock(self.lock_ptr) != 0:
            raise RuntimeError("Failed to release lock")
        return False


class _RLock(_Lock):
    def __enter__(self):
        if libpthread.pthread_rwlock_rdlock(self.lock_ptr) != 0:
            raise RuntimeError("Failed to acquire read lock")


class _WLock(_Lock):
    def __enter__(self):
        if libpthread.pthread_rwlock_wrlock(self.lock_ptr) != 0:
            raise RuntimeError("Failed to acquire write lock")


class RawProcessRwLock:
    """
    A ctypes-based process-shared rwlock using pthread_rwlock_t.
    Can be initialized within an existing memoryview.
    """

    LOCK_SIZE = ctypes.sizeof(PthreadRwlock)

    def __init__(self, mv: memoryview, initialize=False):
        if len(mv) < self.LOCK_SIZE:
            raise ValueError(f"Memory view must be at least {self.LOCK_SIZE} bytes.")

        # Create a ctypes array from the memoryview's buffer
        c_array = (ctypes.c_byte * self.LOCK_SIZE).from_buffer(mv)
        # Get the memory address of that array
        address = ctypes.addressof(c_array)
        # Cast the address to our lock pointer type
        self.lock_ptr = ctypes.cast(address, PthreadRwlock_p)

        if initialize:
            # Initialize the lock with process-shared attribute
            attr = PthreadRwlockAttr()
            if libpthread.pthread_rwlockattr_init(ctypes.byref(attr)) != 0:
                raise RuntimeError("Failed to init rwlock attr")
            if (
                    libpthread.pthread_rwlockattr_setpshared(
                        ctypes.byref(attr), PTHREAD_PROCESS_SHARED
                    )
                    != 0
            ):
                raise RuntimeError("Failed to set pshared attr")

            if libpthread.pthread_rwlock_init(self.lock_ptr, ctypes.byref(attr)) != 0:
                raise RuntimeError("Failed to init rwlock")

    def acquire_read(self) -> _RLock:
        return _RLock(self.lock_ptr)

    def acquire_write(self) -> _WLock:
        return _WLock(self.lock_ptr)

    def release(self):
        if libpthread.pthread_rwlock_unlock(self.lock_ptr) != 0:
            raise RuntimeError("Failed to release lock")

    def destroy(self):
        libpthread.pthread_rwlock_destroy(self.lock_ptr)
