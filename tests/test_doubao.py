import asyncio
import gzip
import json
import struct
import sys
import types
import unittest

from ai_japanese_interview_assistant.transcription import LOCAL_PREVIEW_EVENT, run_doubao, _doubao_response


def frame(utterances=(), *, final=False):
    data = gzip.compress(json.dumps({"result": {"utterances": utterances}}).encode())
    return b"\x11" + bytes((0x93 if final else 0x91, 0x11, 0)) + struct.pack(">iI", -1 if final else 1, len(data)) + data


class DoubaoTests(unittest.TestCase):
    def test_stream(self):
        async def run():
            events, sent, ready = [], [], []
            responses = asyncio.Queue()
            responses.put_nowait(frame())
            class Socket:
                async def __aenter__(self):
                    return self
                async def __aexit__(self, *args):
                    pass
                async def send(self, packet):
                    sent.append(packet)
                    if packet[1] == 0x20:
                        responses.put_nowait(frame([{"text":"Why SWT", "end_time":100, "definite":False}]))
                    if packet[1] == 0x22:
                        part = {"text":"Why SWT?", "end_time":150, "definite":True}
                        responses.put_nowait(frame([part]))
                        responses.put_nowait(frame([part], final=True))
                async def recv(self):
                    return await responses.get()
            def connect(url, **opts):
                self.assertTrue(url.endswith("/bigmodel_async"))
                self.assertEqual(opts["additional_headers"]["X-Api-Key"], "test")
                return Socket()
            async def audio():
                yield bytes(6400)
                yield bytes(3200)
            await run_doubao("test", audio(), events.append, lambda: ready.append(True), connect=connect)
            self.assertEqual(ready, [True])
            self.assertEqual([p[1] for p in sent], [0x10, 0x20, 0x22])
            self.assertEqual([e["type"] for e in events],
                             [LOCAL_PREVIEW_EVENT, "conversation.item.input_audio_transcription.completed"])
            self.assertEqual(events[0]["item_id"], events[1]["item_id"])
            self.assertEqual(events[1]["transcript"], "Why SWT?")
        try:
            import websockets.exceptions
        except ImportError:
            from unittest.mock import patch
            errors = types.ModuleType("websockets.exceptions")
            errors.ConnectionClosed = type("ConnectionClosed", (Exception,), {})
            errors.InvalidStatus = type("InvalidStatus", (Exception,), {})
            with patch.dict(sys.modules, {"websockets.exceptions": errors}):
                asyncio.run(run())
        else:
            asyncio.run(run())

    def test_reject_truncated_response(self):
        from ai_japanese_interview_assistant.transcription import RealtimeError
        with self.assertRaises(RealtimeError):
            _doubao_response(frame()[:-1])


if __name__ == "__main__":
    unittest.main()
