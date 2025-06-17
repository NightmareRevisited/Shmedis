from shmedis.index_hash_table import IndexHashTable


class TestIndexHashTable:
    def test_set(self):
        buffer = bytearray(1 << 24)  # 4MB
        mv = memoryview(buffer)
        ht = IndexHashTable(mv)
        ht["test"] = 1
        assert ht["test"] == 1

    def test_delete(self):
        buffer = bytearray(1 << 24)
        mv = memoryview(buffer)
        ht = IndexHashTable(mv)
        ht["test"] = 1
        del ht["test"]
        assert ht["test"] is None
