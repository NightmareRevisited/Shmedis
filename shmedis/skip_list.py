import logging
import random
import struct
import time
from struct import unpack_from
from typing import Optional, Tuple

from shmedis.data_type import BOOL_SIZE, U16_SIZE, U32_SIZE

# Use '>' prefix for big-endian standard sizing.
_LOGGER = logging.getLogger(__name__)

LEVEL_OFFSET = 0
VALUE_OFFSET = 4  # level(1) + padding(3)
POINTERS_OFFSET = 12  # VALUE_OFFSET + VALUE_SIZE

POINTER_SIZE = struct.calcsize(">I")
VALUE_SIZE = struct.calcsize(">II")
NODE_HEADER_SIZE = 4  # level(1) + padding(3)

# Define the maximum space a single node can occupy.
MAX_LEVEL = 16
NODE_DATA_SIZE = VALUE_SIZE + MAX_LEVEL * POINTER_SIZE
NODE_SIZE = NODE_HEADER_SIZE + NODE_DATA_SIZE


class SkipList:
    """
    A Skip List implementation that uses an externally provided memoryview for storage.

    - Element: A tuple of (u32, u32).
    - Sorting: Ascending order based on the difference: value[1] - value[0].
    - Deletion: Nodes are unlinked from the list. The memory segment for the node
                is then ignored and not reclaimed.
    - Byte Order: Big-Endian.
    """

    meta: memoryview
    mv: memoryview

    @property
    def initialized(self) -> bool:
        return unpack_from(">?", self.meta, 0)[0]

    @initialized.setter
    def initialized(self, value: bool):
        struct.pack_into(">?", self.meta, 0, value)

    @property
    def level(self) -> int:
        return unpack_from(">H", self.meta, U16_SIZE)[0]

    @level.setter
    def level(self, value: int):
        struct.pack_into(">H", self.meta, U16_SIZE, value)

    @property
    def element_count(self) -> int:
        return unpack_from(">I", self.meta, U32_SIZE)[0]

    @element_count.setter
    def element_count(self, value: int):
        struct.pack_into(">I", self.meta, U32_SIZE, value)

    @property
    def header_idx(self) -> int:
        return 0

    def __init__(self, buffer_mv: memoryview, max_level=MAX_LEVEL):
        """
        Initializes the Skip List.

        Args:
            buffer_mv (memoryview): A user-provided memoryview for node storage.
            max_level (int): The maximum number of levels in the skip list.
        """
        if len(buffer_mv) < NODE_SIZE:
            raise ValueError("Buffer is too small to hold even a single node.")

        self.meta = buffer_mv[: U32_SIZE * 2]
        self.mv = buffer_mv[U32_SIZE * 2:]
        self.max_level = max_level
        self.max_elements = len(self.mv) // NODE_SIZE

        if not self.initialized:
            self.initialized = True
            # Initialize the header node (located at index 0).
            self._alloc_node(self.max_level, (0, 0))
            header_mv = self._get_node_mv(self.header_idx)

            # Initialize all forward pointers of the header to point to itself (marks end of list).
            forward_offset = POINTERS_OFFSET
            for i in range(self.max_level):
                struct.pack_into(
                    ">I", header_mv, forward_offset + i * POINTER_SIZE, self.header_idx
                )

    def _get_node_mv(self, index: int) -> memoryview:
        start = index * NODE_SIZE
        return self.mv[start: start + NODE_SIZE]

    def _get_level(self, node_mv: memoryview) -> int:
        return struct.unpack_from("B", node_mv, LEVEL_OFFSET)[0]

    def _unpack_value(self, node_mv: memoryview) -> Tuple[int, int]:
        return struct.unpack_from(">II", node_mv, VALUE_OFFSET)

    def _get_forward_ptr(self, node_mv: memoryview, level: int) -> int:
        offset = POINTERS_OFFSET + level * POINTER_SIZE
        return struct.unpack_from(">I", node_mv, offset)[0]

    def _set_forward_ptr(self, node_mv: memoryview, level: int, index: int):
        offset = POINTERS_OFFSET + level * POINTER_SIZE
        struct.pack_into(">I", node_mv, offset, index)

    def _alloc_node(self, level: int, value: tuple) -> int:
        if self.element_count >= self.max_elements:
            self.recycle_fragments()

        index = self.element_count
        node_mv = self._get_node_mv(index)

        # Pack header and value.
        struct.pack_into("B", node_mv, LEVEL_OFFSET, level)
        struct.pack_into(">II", node_mv, VALUE_OFFSET, *value)

        self.element_count += 1
        return index

    def _random_level(self) -> int:
        level = 1
        while random.getrandbits(1) and level < self.max_level:
            level += 1
        return level

    @staticmethod
    def _get_sort_key(value: Tuple[int, int]) -> int:
        return value[1] - value[0]

    def insert(self, value: Tuple[int, int]) -> int:
        """
        Inserts a new value into the skip list.

        Args:
            value: A tuple of two integers to be inserted
            (value will be sorted by value[1] - value[0])

        Returns:
            int: The index of the newly allocated node

        Raises:
            MemoryError: If the buffer is full
        """
        if value[0] > value[1]:
            raise ValueError("start_offset must be smaller than end_offset!")

        update = [0] * self.max_level
        current_idx = self.header_idx
        current_mv = self._get_node_mv(current_idx)

        for i in range(self.level - 1, -1, -1):
            next_idx = self._get_forward_ptr(current_mv, i)
            while next_idx != self.header_idx:
                next_mv = self._get_node_mv(next_idx)
                next_val = self._unpack_value(next_mv)
                if self._get_sort_key(next_val) < self._get_sort_key(value):
                    current_idx = next_idx
                    current_mv = next_mv
                    next_idx = self._get_forward_ptr(current_mv, i)
                else:
                    break
            update[i] = current_idx

        new_level = self._random_level()
        if new_level > self.level:
            for i in range(self.level, new_level):
                update[i] = self.header_idx
            self.level = new_level

        new_node_idx = self._alloc_node(new_level, value)
        new_node_mv = self._get_node_mv(new_node_idx)

        for i in range(new_level):
            update_node_mv = self._get_node_mv(update[i])
            prev_forward_idx = self._get_forward_ptr(update_node_mv, i)
            self._set_forward_ptr(new_node_mv, i, prev_forward_idx)
            self._set_forward_ptr(update_node_mv, i, new_node_idx)

        return new_node_idx

    def search_by_boundary(self, boundary: int) -> Optional[Tuple[int, int]]:
        """Finds the smallest element where (value[1] - value[0]) > boundary."""
        current_idx = self.header_idx
        current_mv = self._get_node_mv(current_idx)

        for i in range(self.level - 1, -1, -1):
            next_idx = self._get_forward_ptr(current_mv, i)
            while next_idx != self.header_idx:
                next_mv = self._get_node_mv(next_idx)
                next_val = self._unpack_value(next_mv)
                if self._get_sort_key(next_val) < boundary:
                    current_idx = next_idx
                    current_mv = next_mv
                    next_idx = self._get_forward_ptr(current_mv, i)
                else:
                    break

        target_idx = self._get_forward_ptr(self._get_node_mv(current_idx), 0)

        if target_idx != self.header_idx:
            return self._unpack_value(self._get_node_mv(target_idx))

        return None

    def delete(self, value: Tuple[int, int]) -> bool:
        """Deletes an element from the skip list (hard delete)."""
        update = [0] * self.max_level
        current_idx = self.header_idx
        current_mv = self._get_node_mv(current_idx)

        for i in range(self.level - 1, -1, -1):
            next_idx = self._get_forward_ptr(current_mv, i)
            while next_idx != self.header_idx:
                next_mv = self._get_node_mv(next_idx)
                next_val = self._unpack_value(next_mv)
                if self._get_sort_key(next_val) < self._get_sort_key(value):
                    current_idx = next_idx
                    current_mv = next_mv
                    next_idx = self._get_forward_ptr(current_mv, i)
                else:
                    break
            update[i] = current_idx

        target_idx = self._get_forward_ptr(self._get_node_mv(current_idx), 0)

        if target_idx != self.header_idx:
            target_mv = self._get_node_mv(target_idx)
            target_val = self._unpack_value(target_mv)

            if target_val == value and self._get_sort_key(
                    target_val
            ) == self._get_sort_key(value):
                target_level = self._get_level(target_mv)
                for i in range(target_level):
                    update_node_mv = self._get_node_mv(update[i])
                    next_ptr_of_target = self._get_forward_ptr(target_mv, i)
                    self._set_forward_ptr(update_node_mv, i, next_ptr_of_target)

                header_mv = self._get_node_mv(self.header_idx)
                while (
                        self.level > 0
                        and self._get_forward_ptr(header_mv, self.level - 1)
                        == self.header_idx
                ):
                    self.level -= 1

                return True
        return False

    def recycle_fragments(self):
        """reinit the skip list to recycle fragments"""
        start_time = time.time()
        val_list = []
        current_idx = self._get_forward_ptr(self._get_node_mv(self.header_idx), 0)
        while current_idx != self.header_idx:
            node_mv = self._get_node_mv(current_idx)
            val_list.append(self._unpack_value(node_mv))
            current_idx = self._get_forward_ptr(node_mv, 0)

        struct.pack_into(f">?{len(self.meta) - BOOL_SIZE}x", self.meta, 0, True)
        # Initialize the header node (located at index 0).
        self._alloc_node(self.max_level, (0, 0))
        header_mv = self._get_node_mv(self.header_idx)

        # Initialize all forward pointers of the header to point to itself (marks end of list).
        forward_offset = POINTERS_OFFSET
        for i in range(self.max_level):
            struct.pack_into(
                ">I", header_mv, forward_offset + i * POINTER_SIZE, self.header_idx
            )

        for val in val_list:
            self.insert(val)

        end_time = time.time()
        _LOGGER.info(
            f"Shmedis SkipList Recycle fragments cost: {int(1000000 * (end_time - start_time))}us"
        )

    def _display(self):
        """Prints the structure of the skip list for debugging purposes."""
        print(
            f"\nSkipList (level={self.level}, nodes_allocated={self.element_count}/{self.max_elements}):"
        )
        # FIX: Also correct the display loop to avoid potential errors if used elsewhere.
        for i in range(self.level - 1, -1, -1):
            print(f"Level {i}: ", end="")
            current_idx = self._get_forward_ptr(self._get_node_mv(self.header_idx), i)
            while current_idx != self.header_idx:
                node_mv = self._get_node_mv(current_idx)
                val = self._unpack_value(node_mv)

                print(f"{val} (size={self._get_sort_key(val)})", end=" -> ")

                current_idx = self._get_forward_ptr(node_mv, i)
            print("NIL")
