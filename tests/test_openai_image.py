"""GPTImage2Client 단위 테스트 (openai SDK mock)."""
import sys
import io
import base64
import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.openai_image.client import (
    GPTImage2Client,
    GPTImage2Result,
    VerificationResult,
    GPTImage2NoCreditError,
    DEFAULT_MODEL,
    snap_size,
)


def _fake_b64_image(size: int = 64) -> str:
    """테스트용 작은 PNG의 base64."""
    from PIL import Image
    img = Image.new("RGB", (size, size), (200, 100, 50))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


class TestEnhance:
    def test_enhance_returns_result_with_bytes(self):
        c = GPTImage2Client(api_key="sk-test")
        b64 = _fake_b64_image()
        fake_resp = MagicMock()
        fake_resp.data = [MagicMock(b64_json=b64)]

        with patch.object(c._client.images, "edit", return_value=fake_resp) as m:
            r = c.enhance(
                image_bytes=b"\x89PNG\r\n\x1a\nfake",
                prompt="enhance please",
                quality="medium",
                size="1024x1024",
            )

        assert isinstance(r, GPTImage2Result)
        assert r.enhanced_bytes == base64.b64decode(b64)
        assert r.quality == "medium"
        assert r.prompt_used == "enhance please"
        args, kwargs = m.call_args
        assert kwargs["model"] == DEFAULT_MODEL == "gpt-image-2.5-flare"
        assert kwargs["prompt"] == "enhance please"
        assert kwargs["quality"] == "medium"
        assert kwargs["size"] == "1024x1024"
        # gpt-image-2/2.5 는 input_fidelity 를 지원하지 않는다 → 보내지 않는다
        assert "input_fidelity" not in kwargs

    def test_enhance_passes_quality_high(self):
        c = GPTImage2Client(api_key="sk-test")
        b64 = _fake_b64_image()
        fake_resp = MagicMock()
        fake_resp.data = [MagicMock(b64_json=b64)]
        with patch.object(c._client.images, "edit", return_value=fake_resp) as m:
            c.enhance(b"\x89PNG", prompt="x", quality="hd")
        assert m.call_args.kwargs["quality"] == "hd"

    def test_enhance_402_raises_no_credit_error(self):
        from openai import APIStatusError
        c = GPTImage2Client(api_key="sk-test")
        err = APIStatusError(
            message="credit balance too low",
            response=MagicMock(status_code=402),
            body={"error": {"code": "insufficient_quota"}},
        )
        with patch.object(c._client.images, "edit", side_effect=err):
            with pytest.raises(GPTImage2NoCreditError):
                c.enhance(b"\x89PNG", prompt="x")


class TestVerify:
    def _make_resp(self, content: str):
        msg = MagicMock(content=content)
        choice = MagicMock(message=msg)
        return MagicMock(choices=[choice])

    def test_verify_parses_safe_json(self):
        c = GPTImage2Client(api_key="sk-test")
        resp = self._make_resp('{"safe": true, "issues": []}')
        with patch.object(c._client.chat.completions, "create", return_value=resp):
            r = c.verify(b"orig", b"enh", prompt="check")
        assert r.safe is True
        assert r.issues == []

    def test_verify_parses_unsafe_with_issues(self):
        c = GPTImage2Client(api_key="sk-test")
        resp = self._make_resp(
            '{"safe": false, "issues": ["로고 흐려짐", "패턴 단순화"]}')
        with patch.object(c._client.chat.completions, "create", return_value=resp):
            r = c.verify(b"orig", b"enh", prompt="check")
        assert r.safe is False
        assert "로고 흐려짐" in r.issues
        assert "패턴 단순화" in r.issues

    def test_verify_invalid_json_falls_back_to_unsafe(self):
        c = GPTImage2Client(api_key="sk-test")
        resp = self._make_resp("this is not JSON")
        with patch.object(c._client.chat.completions, "create", return_value=resp):
            r = c.verify(b"orig", b"enh", prompt="check")
        assert r.safe is False
        assert any("파싱" in s for s in r.issues)

    def test_verify_passes_two_images_in_request(self):
        c = GPTImage2Client(api_key="sk-test")
        resp = self._make_resp('{"safe": true, "issues": []}')
        with patch.object(c._client.chat.completions, "create", return_value=resp) as m:
            c.verify(b"AAA", b"BBB", prompt="compare")
        kwargs = m.call_args.kwargs
        assert kwargs["model"] == "gpt-4o-mini"
        msgs = kwargs["messages"]
        content = msgs[0]["content"]
        types = [c["type"] for c in content]
        assert types == ["text", "image_url", "image_url"]


class TestEnhanceAndVerify:
    def test_runs_both_in_order(self):
        c = GPTImage2Client(api_key="sk-test")
        b64 = _fake_b64_image()
        edit_resp = MagicMock()
        edit_resp.data = [MagicMock(b64_json=b64)]
        verify_msg = MagicMock(content='{"safe": true, "issues": []}')
        verify_resp = MagicMock(choices=[MagicMock(message=verify_msg)])
        with patch.object(c._client.images, "edit", return_value=edit_resp), \
             patch.object(c._client.chat.completions, "create",
                          return_value=verify_resp):
            enh, ver = c.enhance_and_verify(
                image_bytes=b"orig",
                enhance_prompt="boost",
                verify_prompt="compare",
                quality="medium",
            )
        assert isinstance(enh, GPTImage2Result)
        assert isinstance(ver, VerificationResult)
        assert ver.safe is True

    def test_returns_none_verification_when_disabled(self):
        c = GPTImage2Client(api_key="sk-test")
        b64 = _fake_b64_image()
        edit_resp = MagicMock()
        edit_resp.data = [MagicMock(b64_json=b64)]
        with patch.object(c._client.images, "edit", return_value=edit_resp):
            enh, ver = c.enhance_and_verify(
                image_bytes=b"orig",
                enhance_prompt="boost",
                verify_prompt="compare",
                quality="medium",
                run_verification=False,
            )
        assert ver is None


class TestModelAndSize:
    """gpt-image-2.5 전환 — 모델 선택 / 품질 폴백 / 크기 보정."""

    def _resp(self):
        r = MagicMock()
        r.data = [MagicMock(b64_json=_fake_b64_image())]
        r.usage = MagicMock(output_tokens=439)
        return r

    def test_model_override_per_call(self):
        c = GPTImage2Client(api_key="sk-test")
        with patch.object(c._client.images, "edit",
                          return_value=self._resp()) as m:
            r = c.enhance(b"fakePNG", prompt="x",
                          model="gpt-image-2.5-sunburst", size="1024x1024")
        assert m.call_args.kwargs["model"] == "gpt-image-2.5-sunburst"
        assert r.model == "gpt-image-2.5-sunburst"

    def test_legacy_model_downgrades_xhigh(self):
        """2.0 모델에 xhigh/max 가 오면 high 로 내려간다."""
        c = GPTImage2Client(api_key="sk-test", model="gpt-image-2")
        with patch.object(c._client.images, "edit",
                          return_value=self._resp()) as m:
            c.enhance(b"fakePNG", prompt="x", quality="max",
                      size="1024x1024")
        assert m.call_args.kwargs["quality"] == "high"

    def test_xhigh_kept_for_25(self):
        c = GPTImage2Client(api_key="sk-test")
        with patch.object(c._client.images, "edit",
                          return_value=self._resp()) as m:
            c.enhance(b"fakePNG", prompt="x", quality="xhigh",
                      size="1024x1024")
        assert m.call_args.kwargs["quality"] == "xhigh"

    def test_size_match_uses_source_dimensions(self):
        """size="match" 면 원본 크기를 16의 배수로 맞춰 보낸다 (2250 → 2256)."""
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (2250, 2250), "white").save(buf, format="PNG")
        c = GPTImage2Client(api_key="sk-test")
        with patch.object(c._client.images, "edit",
                          return_value=self._resp()) as m:
            c.enhance(buf.getvalue(), prompt="x", size="match")
        assert m.call_args.kwargs["size"] == "2256x2256"

    def test_cost_from_usage_tokens(self):
        """비용은 응답 usage 의 출력 토큰으로 계산한다 ($30/1M)."""
        c = GPTImage2Client(api_key="sk-test")
        with patch.object(c._client.images, "edit", return_value=self._resp()):
            r = c.enhance(b"fakePNG", prompt="x", size="1024x1024")
        assert r.output_tokens == 439
        # 표시용으로 소수 4자리에서 반올림한다
        assert abs(r.cost_estimate_usd - 439 * 30 / 1_000_000) < 1e-4

    @pytest.mark.parametrize("wh,expected", [
        ((2250, 2250), "2256x2256"),
        ((1024, 1024), "1024x1024"),
        ((5000, 5000), "2880x2880"),      # 최대 픽셀(8.29M) 이내로 축소
        ((400, 400), "816x816"),          # 최소 픽셀(0.65M) 이상으로 확대
    ])
    def test_snap_size(self, wh, expected):
        s = snap_size(*wh)
        assert s == expected
        w, h = (int(v) for v in s.split("x"))
        assert w % 16 == 0 and h % 16 == 0
        assert 655_360 <= w * h <= 8_294_400
        assert max(w, h) <= 3840
