from types import SimpleNamespace

import pytest

from forge.artdirector import review
from forge.illustrator import Ideogram, IllustratorError


class R:
    def __init__(self, code=200, data=None, content=b""):
        self.status_code, self._d, self.content, self.text = code, data, content, str(data)

    def json(self):
        return self._d

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class Sess:
    def __init__(self, post_resp):
        self.post_resp, self.posts, self.gets = post_resp, [], []

    def post(self, url, headers=None, files=None, timeout=None):
        self.posts.append((url, headers, files))
        return self.post_resp

    def get(self, url, timeout=None):
        self.gets.append(url)
        return R(content=b"PNGDATA")


def test_ideogram_request_and_download():
    s = Sess(R(data={"data": [{"url": "https://ideo/1.png", "is_image_safe": True}, {"url": "https://ideo/2.png", "is_image_safe": False}]}))
    imgs = Ideogram("KEY", session=s).generate("a snook", n=2, speed="TURBO", upscale="X2")
    url, headers, files = s.posts[0]
    assert url.endswith("/v1/ideogram-v3/generate-transparent") and headers == {"Api-Key": "KEY"}
    assert files["prompt"][1] == "a snook" and files["num_images"][1] == "2" and files["rendering_speed"][1] == "TURBO"
    assert imgs == [b"PNGDATA"] and s.gets == ["https://ideo/1.png"]  # unsafe image skipped


def test_ideogram_error_is_raised():
    with pytest.raises(IllustratorError):
        Ideogram("KEY", session=Sess(R(code=401, data={"message": "bad key"}))).generate("x")


class FakeClient:
    def __init__(self, reply):
        self.reply, self.sent = reply, None
        self.messages = self

    def create(self, model, max_tokens, messages):
        self.sent = messages
        return SimpleNamespace(content=[SimpleNamespace(text=self.reply)])


def test_art_director_picks_best_passing_option():
    c = FakeClient('{"scores":[9,8],"text_ok":[false,true],"best":0,"notes":"option 0 misspells TIDES"}')
    v = review([b"a", b"b"], "Tides Wait For No One", "anglers", "m", client=c)
    assert v["best"] == 1  # 0 scored higher but has a text error
    imgs = [p for p in c.sent[0]["content"] if p["type"] == "image"]
    assert len(imgs) == 2 and imgs[0]["source"]["media_type"] == "image/jpeg"


def test_art_director_rejects_all_below_bar():
    v = review([b"a"], "x", "n", "m", client=FakeClient('{"scores":[5],"text_ok":[true],"notes":"muddy"}'))
    assert v["best"] is None
