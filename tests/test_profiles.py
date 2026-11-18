import asyncio
import json

import pytest

from ai_japanese_interview_assistant.interview import InterviewService
from ai_japanese_interview_assistant.profiles import Fact, ProfileError, ProfileStore, select_facts
from ai_japanese_interview_assistant.services import ServiceError


def test_profile_round_trip_and_delete(tmp_path):
    store = ProfileStore(tmp_path / "profile.json")
    assert store.load() == ()
    facts = (Fact("a", "education", "工学を学びました。", "我学习了工学。"),)
    store.save(facts)
    assert ProfileStore(store.path).load() == facts
    store.save(())
    assert store.load() == ()


def test_corrupted_profile_is_preserved(tmp_path):
    store = ProfileStore(tmp_path / "profile.json")
    store.path.write_text("{", encoding="utf-8")
    with pytest.raises(ProfileError, match="损坏"):
        store.load()
    assert store.path.read_text(encoding="utf-8") == "{"


def test_related_facts_are_ranked_and_limited_to_two():
    general = Fact("a", "project", "回路を設計しました。", "我设计了电路。")
    matching = Fact("b", "project", "無線通信を試しました。", "我试验了无线通信。", ("無線",))
    third = Fact("c", "project", "基板を作りました。", "我制作了电路板。", ("基板",))
    other = Fact("d", "skill", "Python を使います。", "我使用 Python。")
    assert select_facts((general, matching, third, other), "無線の経験は？", ["project"]) == (matching, general)
    assert select_facts((matching, third), "無線の経験は？", ["project"]) == (matching,)


class InterviewBackend:
    def __init__(self, fact_id):
        self.fact_id = fact_id
        self.payloads = {}

    async def structured(self, purpose, prompt, value, schema, max_tokens):
        self.payloads[purpose] = value
        if purpose == "question":
            return {"question": True, "personal": True, "categories": ["project"]}
        if purpose == "draft":
            return {"before_ja": "お答えします。", "before_zh": "我来回答。",
                    "after_ja": "", "after_zh": "", "fact_ids": [self.fact_id]}
        return {"safe": True}


def test_only_authorized_fact_is_sent_and_rendered_verbatim():
    backend = InterviewBackend("a")
    facts = (Fact("a", "project", "測定を担当しました。", "我负责测量。"),)
    answer = asyncio.run(InterviewService(backend).suggest("役割は？", automatic=False, facts=facts))
    payload = json.loads(backend.payloads["draft"])
    assert payload["facts"] == [{"id": "a", "ja": "測定を担当しました。", "zh": "我负责测量。"}]
    assert answer.ja.endswith("測定を担当しました。")
    assert answer.zh.endswith("我负责测量。")


def test_unknown_fact_id_stops_suggestion_before_verification():
    backend = InterviewBackend("unknown")
    facts = (Fact("a", "project", "測定を担当しました。", "我负责测量。"),)
    with pytest.raises(ServiceError, match="核验"):
        asyncio.run(InterviewService(backend).suggest("役割は？", automatic=False, facts=facts))
    assert "verify_answer" not in backend.payloads


def test_revocation_during_classification_prevents_fact_upload():
    allowed = True

    class RevokingBackend(InterviewBackend):
        async def structured(self, purpose, prompt, value, schema, max_tokens):
            nonlocal allowed
            result = await super().structured(purpose, prompt, value, schema, max_tokens)
            if purpose == "question":
                allowed = False
            return result

    backend = RevokingBackend("a")
    facts = (Fact("a", "project", "測定を担当しました。", "我负责测量。"),)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(InterviewService(backend).suggest(
            "役割は？", automatic=False, facts=facts, allowed=lambda: allowed,
        ))
    assert list(backend.payloads) == ["question"]
