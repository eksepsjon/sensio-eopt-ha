"""
Tests for the SMUX protocol layer (sensio_eopt/local.py).
No network connection required — all tests use in-process mocks.
"""

import pytest
from sensio_eopt.local import _smux_encode, _smux_parse, LocalClient


# ---------------------------------------------------------------------------
# SMUX framing helpers
# ---------------------------------------------------------------------------

class TestSmuxEncode:
    def test_simple_message(self):
        assert _smux_encode("hello") == b"\x01hello\x02"

    def test_new_state_command(self):
        assert _smux_encode("new_state B_LightOn 0") == b"\x01new_state B_LightOn 0\x02"

    def test_set_value_command(self):
        assert _smux_encode("set_value M_D_MyDimmer_Val 50") == (
            b"\x01set_value M_D_MyDimmer_Val 50\x02"
        )

    def test_encoding_is_cp1252(self):
        # cp1252 specific: \xa3 = £ (pound sign), valid in cp1252
        result = _smux_encode("\xa3")
        assert result == b"\x01\xa3\x02"


class TestSmuxParse:
    def test_single_message(self):
        buf = b"\x01hello\x02"
        msgs, rest = _smux_parse(buf)
        assert msgs == ["hello"]
        assert rest == b""

    def test_two_messages(self):
        buf = b"\x01first\x02\x01second\x02"
        msgs, rest = _smux_parse(buf)
        assert msgs == ["first", "second"]
        assert rest == b""

    def test_incomplete_message(self):
        buf = b"\x01partial"
        msgs, rest = _smux_parse(buf)
        assert msgs == []
        assert rest == b"\x01partial"

    def test_leading_garbage_skipped(self):
        buf = b"garbage\x01msg\x02"
        msgs, rest = _smux_parse(buf)
        assert msgs == ["msg"]
        assert rest == b""

    def test_header_message_stripped(self):
        # \x07{header}\x01{body}\x02 — header is discarded
        buf = b"\x07oid some-guid\x01body text\x02"
        msgs, rest = _smux_parse(buf)
        assert msgs == ["body text"]
        assert rest == b""

    def test_rsn_event(self):
        buf = b"\x01RSN 49633 D_Hall2etgHallTrappEntre 21 1 69 69\x02"
        msgs, rest = _smux_parse(buf)
        assert len(msgs) == 1
        assert "D_Hall2etgHallTrappEntre" in msgs[0]
        assert "69" in msgs[0]

    def test_partial_then_complete(self):
        # Simulate two recv() calls — partial first, then the rest
        chunk1 = b"\x01hello"
        chunk2 = b" world\x02"
        msgs1, rest1 = _smux_parse(chunk1)
        assert msgs1 == []
        msgs2, rest2 = _smux_parse(rest1 + chunk2)
        assert msgs2 == ["hello world"]
        assert rest2 == b""

    def test_empty_buffer(self):
        msgs, rest = _smux_parse(b"")
        assert msgs == []
        assert rest == b""


# ---------------------------------------------------------------------------
# LocalClient.dim() — correct two-message sequence
# ---------------------------------------------------------------------------

class TestLocalClientDim:
    def _make_client(self):
        """Create a LocalClient with a fake socket that records sends."""
        client = LocalClient("127.0.0.1", "tok", "sec")
        sent = []

        class FakeSocket:
            def sendall(self, data):
                sent.append(data)

        client._sock = FakeSocket()
        return client, sent

    def test_dim_sends_set_value_then_new_state(self):
        client, sent = self._make_client()
        client.dim("B_D_Hall2etgHallTrappEntre_SET", 50)
        assert len(sent) == 2
        assert sent[0] == _smux_encode("set_value M_D_Hall2etgHallTrappEntre_Val 50")
        assert sent[1] == _smux_encode("new_state B_D_Hall2etgHallTrappEntre_SET 0")

    def test_dim_zero_turns_off(self):
        client, sent = self._make_client()
        client.dim("B_D_Hall2etgHallTrappEntre_SET", 0)
        assert sent[0] == _smux_encode("set_value M_D_Hall2etgHallTrappEntre_Val 0")

    def test_dim_clamps_to_100(self):
        client, sent = self._make_client()
        client.dim("B_D_Hall2etgHallTrappEntre_SET", 150)
        assert sent[0] == _smux_encode("set_value M_D_Hall2etgHallTrappEntre_Val 100")

    def test_dim_clamps_to_0(self):
        client, sent = self._make_client()
        client.dim("B_D_Hall2etgHallTrappEntre_SET", -10)
        assert sent[0] == _smux_encode("set_value M_D_Hall2etgHallTrappEntre_Val 0")

    def test_dim_wrong_name_raises(self):
        client, _ = self._make_client()
        with pytest.raises(ValueError, match="B_D_.*_SET"):
            client.dim("B_LightOn", 50)

    def test_trigger_sends_new_state(self):
        client, sent = self._make_client()
        client.trigger("B_LightHallTrappEntre_ON")
        assert sent == [_smux_encode("new_state B_LightHallTrappEntre_ON 0")]
