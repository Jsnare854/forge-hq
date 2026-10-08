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


def test_fit_spot_keeps_whole_design_inside_print_area():
    from forge.printify import fit_spot
    art = (3600, 4300)  # tall illustration, like the Ideogram output
    cases = {
        "tee": ((4500, 5400), {"x": 0.5, "top": 0.03, "max_w": 0.85, "max_h": 0.8}),
        "hoodie (wide area)": ((3600, 2850), {"x": 0.5, "top": 0.04, "max_w": 0.72, "max_h": 0.72}),
        "mug side": ((2700, 1050), {"x": 0.25, "y": 0.5, "max_w": 0.4, "max_h": 0.86}),
    }
    for name, (area, spot) in cases.items():
        p = fit_spot(spot, art, area)
        w = p["scale"]
        h = p["scale"] * (art[1] / art[0]) * (area[0] / area[1])
        assert p["x"] - w / 2 >= -1e-6 and p["x"] + w / 2 <= 1 + 1e-6, name
        assert p["y"] - h / 2 >= -1e-6 and p["y"] + h / 2 <= 1 + 1e-6, name
        assert h <= spot["max_h"] + 1e-6 and w <= spot["max_w"] + 1e-6, name


def test_fit_spot_falls_back_to_legacy_placement():
    from forge.printify import fit_spot
    assert fit_spot({"x": 0.5, "y": 0.42, "scale": 0.9}, (100, 100), (10, 10)) == {"x": 0.5, "y": 0.42, "scale": 0.9}
    assert fit_spot({"max_w": 0.8}, None, (10, 10))["scale"] == 0.9


def test_trim_png_removes_empty_margins():
    import io
    from PIL import Image
    from forge.printify import trim_png
    img = Image.new("RGBA", (1000, 1200), (0, 0, 0, 0))
    img.paste((255, 0, 0, 255), (300, 100, 700, 500))
    buf = io.BytesIO(); img.save(buf, "PNG")
    _, w, h = trim_png(buf.getvalue())
    assert 400 <= w <= 420 and 400 <= h <= 420


def _art(color, size=(400, 400)):
    import io
    from PIL import Image
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    img.paste(color + (255,), (50, 50, 350, 350))
    buf = io.BytesIO(); img.save(buf, "PNG")
    return buf.getvalue()


def test_best_shirt_moves_dark_art_off_dark_fabric():
    from forge.illustrator import best_shirt
    from forge.spec import SHIRTS
    navy_text = _art((20, 30, 70))
    assert best_shirt(navy_text, "black", SHIRTS)[0] == "white"
    assert best_shirt(navy_text, "navy", SHIRTS)[0] == "white"
    cream = _art((245, 235, 210))
    assert best_shirt(cream, "white", SHIRTS)[0] == "black"
    orange = _art((230, 120, 30))
    assert best_shirt(orange, "maroon", SHIRTS)[0] == "maroon"  # designer's pick kept when it works


def test_prompt_never_asks_for_a_shirt_or_slashes():
    from forge.illustrator import build_prompt
    p = build_prompt("A smoker grill.", [{"text": "Ask My Smoker"}, {"text": "Not Me"}], "black")
    assert "/" not in p and "t-shirt" not in p.lower()
    assert '"Ask My Smoker" and "Not Me"' in p
