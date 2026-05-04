"""resizer 모듈 단위 테스트."""
import sys
from pathlib import Path
import threading
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.exporter.resizer import BatchCounter


class TestBatchCounter:
    def test_next_returns_sequential_starting_from_one(self):
        c = BatchCounter()
        assert c.next() == 1
        assert c.next() == 2
        assert c.next() == 3

    def test_is_first_only_once(self):
        c = BatchCounter()
        assert c.is_first() is True
        assert c.is_first() is False
        assert c.is_first() is False

    def test_is_first_independent_of_next(self):
        c = BatchCounter()
        c.next()
        c.next()
        assert c.is_first() is True   # next() 호출과 무관

    def test_concurrent_next_no_duplicates(self):
        c = BatchCounter()
        results = []
        lock = threading.Lock()

        def worker():
            n = c.next()
            with lock:
                results.append(n)

        threads = [threading.Thread(target=worker) for _ in range(100)]
        for t in threads: t.start()
        for t in threads: t.join()

        assert sorted(results) == list(range(1, 101))

    def test_concurrent_is_first_only_one_winner(self):
        c = BatchCounter()
        wins = []
        lock = threading.Lock()

        def worker():
            if c.is_first():
                with lock:
                    wins.append(1)

        threads = [threading.Thread(target=worker) for _ in range(50)]
        for t in threads: t.start()
        for t in threads: t.join()

        assert len(wins) == 1
