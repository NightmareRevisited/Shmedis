import struct
import time
from math import ceil

BOOL_SIZE = 1
I8_SIZE = 1
U8_SIZE = 1
I16_SIZE = 2
U16_SIZE = 2
I32_SIZE = 4
U32_SIZE = 4
I64_SIZE = 8
U64_SIZE = 8
FLOAT_SIZE = 4
DOUBLE_SIZE = 8
CPU_ARCH_WIDTH = 8

MAX_LENGTH = 1 << 22

TYPE_SDS = 1


class SDS:
    def __init__(
            self, ptr: int, capacity: int, length: int, expire_time: int, value: bytes
    ):
        self.ptr = ptr
        self.capacity = capacity
        self.length = length
        self.expire_time = expire_time
        self.value = value
        self.type = TYPE_SDS

    @property
    def size(self):
        return U32_SIZE * 4 + self.capacity

    @classmethod
    def deref(cls, buf: memoryview, offset: int):
        """
        Deserialize SDS data from memory buffer at given offset
        Args:
            buf: memory buffer containing serialized SDS data
            offset: starting position in buffer to read from
        Returns:
            SDS: deserialized string object
        """
        ptr = offset
        buf_type, capacity, length, expire_time = struct.unpack_from(
            ">B3xIII", buf, offset
        )
        if buf_type != TYPE_SDS:
            raise TypeError(
                "WRONGTYPE Operation against a key holding the wrong kind of value"
            )
        offset += U32_SIZE * 4
        value = struct.unpack_from(f">{length}s", buf, offset)[0]
        return cls(ptr, capacity, length, expire_time, value)

    @classmethod
    def new(cls, value: bytes, expire_seconds: int = 0):
        """
        Creates a new SDS instance in the provided buffer
        Args:
            value: bytes to store
            expire_seconds: optional expiration seconds
        Returns:
            SDS: newly created string object
        Raises:
            ValueError: if value exceeds MAX_LENGTH
        """
        length = len(value)
        if length > MAX_LENGTH:
            raise ValueError(f"SDS value too long! Max length is {MAX_LENGTH}")

        capacity = ceil(length * 1.25 / CPU_ARCH_WIDTH) * CPU_ARCH_WIDTH
        if expire_seconds > 0:
            expire_time = int(time.time() + expire_seconds)
        else:
            expire_time = 0

        return cls(0, capacity, length, expire_time, value)

    def write(self, buf: memoryview, offset: int):
        """
        Serialize SDS data into memory buffer at given offset
        Args:
            buf: memory buffer to write serialized data to
            offset: starting position in buffer to write to
        """
        self.ptr = offset
        struct.pack_into(
            f">B3xIII{self.length}s",
            buf,
            offset,
            TYPE_SDS,
            self.capacity,
            self.length,
            self.expire_time,
            self.value,
        )

    def can_overwrite(self, new_value: bytes) -> bool:
        """
        Checks if new_value can fit within current capacity
        Args:
            new_value: bytes to write
        Returns:
            bool: True if new_value can fit within current capacity, False otherwise
        """
        new_length = len(new_value)
        return self.capacity >= new_length

    def overwrite(self, buf: memoryview, new_value: bytes, expire_seconds: int = 0) -> bool:
        """
        Overwrites the existing value with new_value if it fits within current capacity
        Args:
            buf: memory buffer to write to
            new_value: bytes to write
        Returns:
            bool: True if write succeeded, False if new_value exceeds capacity
        """
        if expire_seconds > 0:
            expire_time = int(time.time() + expire_seconds)
            struct.pack_into(f">I", buf, self.ptr + 3 * U32_SIZE, expire_time)

        struct.pack_into(f">{len(new_value)}s", buf, self.ptr + 4 * U32_SIZE, new_value)
        return True
