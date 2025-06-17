import struct
import time
from typing import Optional

from data_type import SDS, U32_SIZE
from index_hash_table import IndexHashTable
from lock import RawProcessRwLock
from skip_list import SkipList

try:
    from multiprocessing.shared_memory import SharedMemory
except ImportError:
    from shared_memory import SharedMemory

DEFAULT_CACHE_NAME = "default"
DEFAULT_SHM_SIZE = 1 << 30

LOCK_SIZE = RawProcessRwLock.LOCK_SIZE
META_FORMAT = ">IIIIII"
META_SIZE = LOCK_SIZE + struct.calcsize(META_FORMAT)

DEFAULT_SKIP_LIST_SIZE = 1 << 24
DEFAULT_HASH_TABLE_SIZE = 1 << 24

MIN_FRAGMENT_SIZE = 1 << 5


class Shmedis:
    name: str
    shm: SharedMemory
    lock: RawProcessRwLock
    ht: IndexHashTable
    sl: SkipList

    @property
    def total_size(self):
        return struct.unpack_from(">I", self.shm.buf, LOCK_SIZE)[0]

    @total_size.setter
    def total_size(self, value):
        struct.pack_into(">I", self.shm.buf, LOCK_SIZE, value)

    @property
    def hash_table_offset(self):
        return struct.unpack_from(">I", self.shm.buf, LOCK_SIZE + U32_SIZE)[0]

    @hash_table_offset.setter
    def hash_table_offset(self, value):
        struct.pack_into(">I", self.shm.buf, LOCK_SIZE + U32_SIZE, value)

    @property
    def free_skiplist_head_offset(self):
        return struct.unpack_from(">I", self.shm.buf, LOCK_SIZE + U32_SIZE * 2)[0]

    @free_skiplist_head_offset.setter
    def free_skiplist_head_offset(self, value):
        struct.pack_into(">I", self.shm.buf, LOCK_SIZE + U32_SIZE * 2, value)

    @property
    def heap_top_offset(self):
        return struct.unpack_from(">I", self.shm.buf, LOCK_SIZE + U32_SIZE * 3)[0]

    @heap_top_offset.setter
    def heap_top_offset(self, value):
        struct.pack_into(">I", self.shm.buf, LOCK_SIZE + U32_SIZE * 3, value)

    @property
    def data_area_offset(self):
        return struct.unpack_from(">I", self.shm.buf, LOCK_SIZE + U32_SIZE * 4)[0]

    @data_area_offset.setter
    def data_area_offset(self, value):
        struct.pack_into(">I", self.shm.buf, LOCK_SIZE + U32_SIZE * 4, value)

    def __init__(self, name=DEFAULT_CACHE_NAME, size=DEFAULT_SHM_SIZE):
        self.name = name

        try:
            self.shm: SharedMemory = SharedMemory(name=name, create=True, size=size)

            self.total_size = size
            self.hash_table_offset = META_SIZE
            self.free_skiplist_head_offset = META_SIZE + DEFAULT_HASH_TABLE_SIZE
            self.data_area_offset = (
                    META_SIZE + DEFAULT_HASH_TABLE_SIZE + DEFAULT_SKIP_LIST_SIZE
            )
            self.heap_top_offset = self.data_area_offset
            self.lock = RawProcessRwLock(
                self.shm.buf[: RawProcessRwLock.LOCK_SIZE], True
            )
        except FileExistsError:  # If create=True but it already exists
            self.shm = SharedMemory(name=name, create=False, size=size)
            self.lock = RawProcessRwLock(self.shm.buf[: RawProcessRwLock.LOCK_SIZE])
        except Exception:
            raise

        self.ht = IndexHashTable(
            self.shm.buf[META_SIZE: META_SIZE + DEFAULT_HASH_TABLE_SIZE]
        )
        self.sl = SkipList(
            self.shm.buf[
            META_SIZE
            + DEFAULT_HASH_TABLE_SIZE: META_SIZE
                                       + DEFAULT_HASH_TABLE_SIZE
                                       + DEFAULT_SKIP_LIST_SIZE
            ]
        )

    def __del__(self):
        del self.ht
        del self.sl
        del self.lock
        self.shm.close()

    @classmethod
    def _gen_fragment_start_key(cls, start_ptr: int) -> bytes:
        return f"inner:fg:start:{start_ptr}".encode("utf-8")

    @classmethod
    def _gen_fragment_end_key(cls, end_ptr: int) -> bytes:
        return f"inner:fg:end:{end_ptr}".encode("utf-8")

    def _alloc(self, size: int) -> int:
        """
        Allocates a memory block of the specified size from shared memory.

        Args:
            size: The size of memory block to allocate in bytes

        Returns:
            int: The starting offset of the allocated memory block

        Notes:
            - First tries to find a suitable free fragment from skip list
            - If no suitable fragment found, allocates from heap top
            - Splits fragment if remaining space is larger than MIN_FRAGMENT_SIZE
        """
        free_fragment = self.sl.search_by_boundary(size)
        # try to find free fragment big enough to hold new data
        if free_fragment is not None:
            start_ptr, end_ptr = free_fragment
            self.sl.delete(free_fragment)
            del self.ht[self._gen_fragment_start_key(start_ptr)]
            # if new fragment is big enough, split it
            if end_ptr - start_ptr - size > MIN_FRAGMENT_SIZE:
                self.sl.insert((start_ptr + size, end_ptr))
                self.ht[self._gen_fragment_end_key(start_ptr + size)] = end_ptr
                self.ht[self._gen_fragment_end_key(end_ptr)] = start_ptr + size
            else:
                del self.ht[self._gen_fragment_start_key(end_ptr)]

            return start_ptr

        # if no free fragment found, allocate new one
        start_ptr = self.heap_top_offset
        self.heap_top_offset += size
        return start_ptr

    def _free(self, ptr: int, size: int):
        """
        Frees a memory block and merges adjacent free fragments if possible.

        Args:
            ptr: The starting offset of the memory block to free
            size: The size of the memory block to free in bytes

        Notes:
            - Merges left adjacent fragment if exists by checking hash table
            - Merges right adjacent fragment if exists by checking hash table
            - Inserts the merged fragment into skip list and updates hash table
        """
        end_ptr = ptr + size
        while (left_ptr := self.ht[self._gen_fragment_end_key(ptr)]) is not None:
            self.sl.delete((left_ptr, ptr))
            del self.ht[self._gen_fragment_start_key(left_ptr)]
            del self.ht[self._gen_fragment_end_key(ptr)]
            ptr = left_ptr
        while (right_ptr := self.ht[self._gen_fragment_start_key(end_ptr)]) is not None:
            self.sl.delete((end_ptr, right_ptr))
            del self.ht[self._gen_fragment_start_key(end_ptr)]
            del self.ht[self._gen_fragment_end_key(right_ptr)]
            end_ptr = right_ptr
        self.sl.insert((ptr, end_ptr))
        self.ht[self._gen_fragment_start_key(ptr)] = end_ptr
        self.ht[self._gen_fragment_end_key(end_ptr)] = ptr

    def get(self, key: bytes | str) -> Optional[bytes]:
        """
        Retrieves the value associated with the given key from shared memory.
        cost 5us per get

        Args:
            key: The key to lookup, can be either bytes or string type

        Returns:
            Optional[bytes]: The value if key exists and not expired, None otherwise

        Notes:
            - Automatically handles key conversion from string to bytes
            - Checks expiration time and removes expired entries
            - Process-safe operation using read lock
        """
        if isinstance(key, str):
            key = key.encode("utf-8")
        expired = False

        with self.lock.acquire_read():
            data_ptr = self.ht[key]
            if data_ptr is None:
                return None

            sds = SDS.deref(self.shm.buf, data_ptr)
            if sds.expire_time > 0 and sds.expire_time < time.time():
                expired = True

        if expired:
            self.delete(key)
            return None

        return sds.value

    def set(self, key: bytes | str, value: bytes, ex: int = 0):
        """
        Sets a key-value pair in shared memory with optional expiration time.
        Cost 11us per create

        Args:
            key: The key to set, can be either bytes or string type
            value: The value to store as bytes
            ex: Expiration time in seconds (0 means no expiration)

        Notes:
            - Automatically handles key conversion from string to bytes
            - Overwrites existing value if key exists and not expired
            - Allocates new memory block if key doesn't exist or expired
            - Process-safe operation using read-write lock
        """
        create = True
        with self.lock.acquire_write():
            data_ptr = self.ht[key]
            if data_ptr is not None:
                old_sds = SDS.deref(self.shm.buf, data_ptr)
                if (
                        old_sds.expire_time == 0
                        or old_sds.expire_time > time.time()
                        or old_sds.can_overwrite(value)
                ):
                    create = False

            if not create:
                old_sds.overwrite(self.shm.buf, value)
            else:
                new_sds = SDS.new(value, ex)
                sds_ptr = self._alloc(new_sds.size)
                new_sds.write(self.shm.buf, sds_ptr)
                self.ht[key] = sds_ptr

    def delete(self, key: bytes | str):
        """
        Deletes the key-value pair from shared memory and frees the allocated space.
        Cost 60us per delete

        Args:
            key: The key to delete, can be either bytes or string type

        Notes:
            - Automatically handles key conversion from string to bytes
            - Removes the key from hash table and frees the SDS memory block
            - Process-safe operation using read lock
        """
        with self.lock.acquire_write():
            data_ptr = self.ht[key]
            if data_ptr is not None:
                del self.ht[key]
                sds = SDS.deref(self.shm.buf, data_ptr)
                self._free(sds.ptr, sds.size)
