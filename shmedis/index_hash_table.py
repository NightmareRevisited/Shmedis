import struct

import xxhash

from data_type import U64_SIZE

# Use '>' prefix for big-endian standard sizing.
R_LOCK = 1
RW_LOCK = 2


class HashTableNode:
    ptr: int
    key_hash: bytes
    value: int

    format = ">16sQ"
    size = struct.calcsize(format)

    def __init__(self, ptr: int, key_hash: bytes, value: int):
        self.ptr = ptr
        self.key_hash = key_hash
        self.value = value

    @classmethod
    def deref(cls, buf: memoryview, offset: int):
        ptr = offset
        key_hash, value = struct.unpack_from(f">16sQ", buf, offset)
        return cls(ptr, key_hash, value)


DEFAULT_HASH_SLOT_NUMBER = 1 << 14


class IndexHashTable:
    """
    Hash table with only key lock.
    Table lock between multiprocessing cost too much.
    Key lock is enough for only 2 situations: read data, or read null.
    """

    buf: memoryview
    max_bytes: int
    slot_number: int
    slot_size: int

    slot_head_format = ">Q"
    slot_head_size = struct.calcsize(slot_head_format)

    def __init__(self, buf: memoryview, *, slot_number=DEFAULT_HASH_SLOT_NUMBER):
        self.buf = buf
        self.slot_number = slot_number
        self.slot_size = int(len(buf) / slot_number)

    def __getitem__(self, key: str | bytes):
        """
        Get the value associated with the given key from the hash table.

        Args:
            key: The key to look up in the hash table

        Returns:
            The integer value associated with the key, or None if key not found
        """
        slot = xxhash.xxh32(key, seed=0).intdigest() % self.slot_number
        key_hash: bytes = xxhash.xxh128_digest(key)
        readable_bytes = struct.unpack_from(">Q", self.buf, slot * self.slot_size)[0]

        node_value = None
        offset = slot * self.slot_size + U64_SIZE
        while readable_bytes > 0:
            node = HashTableNode.deref(self.buf, offset)
            if node.key_hash == key_hash:
                node_value = node.value
                break
            offset += node.size
            readable_bytes -= node.size

        return node_value

    def __setitem__(self, key: str | bytes, new_value: int):
        """
        Set the value associated with the given key in the hash table.

        Args:
            key: The key to set in the hash table
            new_value: The integer value to associate with the key

        Raises:
            KeyError: If key is empty or too long
            MemoryError: If no space left in slot for new key
        """
        key_hash: bytes = xxhash.xxh128_digest(key)
        slot = xxhash.xxh32(key, seed=0).intdigest() % self.slot_number
        used_bytes = struct.unpack_from(">Q", self.buf, slot * self.slot_size)[0]
        readable_bytes = used_bytes

        offset = slot * self.slot_size + U64_SIZE
        create = True
        while readable_bytes > 0:
            node = HashTableNode.deref(self.buf, offset)
            if node.key_hash == key_hash:
                create = False
                struct.pack_into(
                    ">Q", self.buf, node.ptr + 16, new_value
                )
                break
            offset += node.size
            readable_bytes -= node.size
        if create:
            if offset + HashTableNode.size > (slot + 1) * self.slot_size:
                raise MemoryError("No enough space to insert key!")
            struct.pack_into(
                HashTableNode.format, self.buf, offset, key_hash, new_value
            )
            struct.pack_into(
                ">Q",
                self.buf,
                slot * self.slot_size,
                used_bytes + HashTableNode.size,
            )

    def __delitem__(self, key: str | bytes):
        """
        Delete the key-value pair associated with the given key from the hash table.

        Args:
            key: The key to delete from the hash table
        """
        key_hash: bytes = xxhash.xxh128_digest(key)
        slot = xxhash.xxh32(key, seed=0).intdigest() % self.slot_number
        used_bytes = struct.unpack_from(">Q", self.buf, slot * self.slot_size)[0]
        readable_bytes = used_bytes
        offset = slot * self.slot_size + U64_SIZE

        while readable_bytes > 0:
            node = HashTableNode.deref(self.buf, offset)
            if node.key_hash == key_hash:
                struct.pack_into(
                    f">{used_bytes - node.size}s",
                    self.buf,
                    offset,
                    bytes(
                        self.buf[
                        offset
                        + node.size: slot * self.slot_size
                                     + U64_SIZE
                                     + used_bytes
                        ]
                    ),
                )
                used_bytes -= node.size
                break
            offset += node.size
            readable_bytes -= node.size

        struct.pack_into(
            ">Q",
            self.buf,
            slot * self.slot_size,
            used_bytes,
        )
