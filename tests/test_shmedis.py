import time

import pytest
from shmedis import Shmedis

shmedis: Shmedis = None


class TestShmedis:
    def setup_class(self):
        global shmedis
        shmedis = Shmedis()

    @pytest.mark.run(order=1)
    def test_set(self):
        shmedis.set("test", b"test1")
        assert shmedis.get("test") == b"test1"

    @pytest.mark.run(order=2)
    def test_set_update(self):
        shmedis.set("test", b"test2")
        assert shmedis.get("test") == b"test2"

    @pytest.mark.run(order=3)
    def test_delete(self):
        shmedis.delete("test")
        assert shmedis.get("test") is None

    @pytest.mark.run(order=4)
    def test_set_nx(self):
        shmedis.set("test", b"test4", nx=True)
        set_response = shmedis.set("test", b"test5", nx=True)
        assert not set_response
        assert shmedis.get("test") == b"test4"

    @pytest.mark.run(order=5)
    def test_set_ex(self):
        shmedis.set("test", b"test6", ex=1)
        assert shmedis.get("test") == b"test6"
        time.sleep(2)
        assert shmedis.get("test") is None

    def teardown_class(self):
        shmedis.unlink()
