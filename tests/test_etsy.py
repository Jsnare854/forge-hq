import time

from forge.etsy import Etsy, enrich


class Resp:
    def __init__(self, data, code=200):
        self._d, self.status_code = data, code

    def json(self):
        return self._d

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class Sess:
    def __init__(self):
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((params, headers))
        now = time.time()
        return Resp({"count": 18432, "results": [
            {"price": {"amount": 2499, "divisor": 100}, "num_favorers": 120, "created_timestamp": now - 10 * 86400},
            {"price": {"amount": 2999, "divisor": 100}, "num_favorers": 40, "created_timestamp": now - 400 * 86400},
            {"price": {"amount": 2799, "divisor": 100}, "num_favorers": 0, "created_timestamp": now - 30 * 86400},
        ]})


def test_search_stats_and_enrich():
    s = Sess()
    e = Etsy("key:secret", session=s)
    st = e.search_stats("icu nurse shirt")
    assert st == {"phrase": "icu nurse shirt", "active_listings": 18432, "median_price": 27.99,
                  "avg_favorites_top": 53.3, "new_in_top_90d": 2, "sampled": 3}
    assert s.calls[0][1] == {"x-api-key": "key:secret"}
    c = enrich(e, [{"niche": "n", "searchPhrases": ["a", "b"]}])
    assert len(c[0]["etsy"]) == 2
    assert enrich(None, [{"niche": "n"}]) == [{"niche": "n"}]
