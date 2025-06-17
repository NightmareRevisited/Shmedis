# Shmedis

[](https://www.google.com/search?q=https://badge.fury.io/py/shmedis)
[](https://opensource.org/licenses/MIT)

**Shmedis** is a high-performance, in-memory caching library for Python that behaves like Redis but leverages shared
memory to allow for efficient data sharing between processes on the same machine. It provides a simple, dictionary-like
interface for storing and retrieving Python objects, making it an ideal solution for inter-process communication and
fast-caching scenarios.

## Features

* **Redis-like API**: Offers a familiar and intuitive API with methods like `set`, `get`, and `delete`.
* **Shared Memory Backend**: Utilizes `multiprocessing.SharedMemory` for extremely fast data access across different
  processes, eliminating the need for socket communication or serialization overhead.
* **Process-Safe**: Implements robust process-safe locking mechanisms using pthread read-write locks (
  `pthread_rwlock_t`), ensuring data integrity during concurrent access.
* **Efficient Memory Management**: Employs a sophisticated memory allocation strategy using a skip list to manage free
  memory fragments, reducing fragmentation and optimizing memory usage.
* **Fast Key Lookups**: Uses a custom hash table implementation (`IndexHashTable`) with `xxhash` for rapid key
  retrieval.
* **Built-in Expiration**: Supports setting an expiration time for cached items.

## How It Works

Shmedis orchestrates several low-level components to create a high-performance cache:

1. **Shared Memory Block**: A large chunk of memory is allocated using `multiprocessing.SharedMemory`, which is
   accessible by multiple processes. This block is partitioned into several areas:

    * **Metadata Area**: Stores essential information about the cache, such as total size, offsets to other data
      structures, and the heap top.
    * **Lock Area**: Contains a process-shared read-write lock (`RawProcessRwLock`) to manage concurrent access.
    * **Index Hash Table**: A fixed-size hash table that maps keys to the memory addresses of their corresponding
      values.
    * **Free-Memory Skip List**: A skip list that keeps track of available memory fragments, enabling efficient
      allocation and deallocation.
    * **Data Area**: The primary region where the actual key-value data is stored.

2. **Data Storage (`SDS`)**: Values are stored using a custom dynamic string-like structure called `SDS` (Simple Dynamic
   String), which is inspired by Redis's own string implementation. Each `SDS` object contains metadata like capacity,
   length, and an optional expiration timestamp.

3. **Memory Allocation and Deallocation**:

    * When a new item is added, Shmedis first attempts to find a suitable free memory block from the skip list.
    * If no appropriately sized fragment is available, it allocates a new block from the top of the heap.
    * When an item is deleted, its memory block is returned to the skip list. The system will also try to merge it with
      any adjacent free blocks to create larger contiguous free spaces.

4. **Concurrency**: To prevent race conditions and ensure data consistency, all read and write operations are protected
   by a `pthread_rwlock_t`. This allows multiple processes to read data simultaneously but ensures that write operations
   have exclusive access.

## Installation

You can install Shmedis directly from PyPI:

```bash
pip install shmedis
```

## Usage

Using Shmedis is straightforward. Here's a basic example:

```python
import os
from multiprocessing import Process
from shmedis import Shmedis


def writer_process(cache_name):
    # Connect to the same shared memory cache
    cache = Shmedis(name=cache_name)

    # Set some values
    cache.set(b'mykey', b'hello world')
    cache.set('another_key', 'with a string value'.encode('utf-8'), ex=5)  # Expires in 5 seconds
    print(f"[Writer PID: {os.getpid()}] Set two keys.")


def reader_process(cache_name):
    # Connect to the same shared memory cache
    cache = Shmedis(name=cache_name)

    # Get a value
    value = cache.get(b'mykey')
    if value:
        print(f"[Reader PID: {os.getpid()}] Got value: {value.decode('utf-8')}")

    # Get another value
    another_value = cache.get('another_key')
    if another_value:
        print(f"[Reader PID: {os.getpid()}] Got another_value: {another_value.decode('utf-8')}")


if __name__ == "__main__":
    cache_name = "my_shared_cache"

    # Create the cache instance in the main process.
    # This will create the shared memory block.
    main_cache = Shmedis(name=cache_name, size=1024 * 1024)  # 1MB cache

    # Create and start writer and reader processes
    writer = Process(target=writer_process, args=(cache_name,))
    reader = Process(target=reader_process, args=(cache_name,))

    writer.start()
    writer.join()

    reader.start()
    reader.join()

    # Clean up the shared memory
    main_cache.shm.unlink()

```

## API Reference

### `Shmedis(name: str = "default", size: int = 1 << 30)`

* **`name`**: A unique name for the shared memory block.
* **`size`**: The total size in bytes to allocate for the cache.

### Methods

* **`set(key: bytes | str, value: bytes, ex: int = 0, nx: bool = False)`**:
  Stores a key-value pair.

    * `key`: The key for the item (can be `str` or `bytes`).
    * `value`: The value to store (`bytes`).
    * `ex`: Optional expiration time in seconds.
    * `nx`: Set key if not exist or Fail

  Return `True` if set success.

* **`get(key: bytes | str) -> Optional[bytes]`**:
  Retrieves the value for a given key. Returns `None` if the key does not exist or has expired.

* **`delete(key: bytes | str)`**:
  Removes a key-value pair from the cache and frees the associated memory.

## Contributing

Contributions are welcome\! If you find a bug or have a feature request, please open an issue on the GitHub repository.

## License

This project is licensed under the APACHE-2.0 License. See the `LICENSE-APACHE` file for details.