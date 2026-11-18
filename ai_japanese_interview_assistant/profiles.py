"""Local, versioned profile storage and deterministic fact selection."""
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile


CATEGORIES = ("education", "skill", "experience", "project", "target")


class ProfileError(Exception):
    """Safe profile failure message."""


@dataclass(frozen=True)
class Fact:
    id: str
    category: str
    ja: str
    zh: str
    tags: tuple[str, ...] = ()


def app_directory():
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        raise ProfileError("Windows 本地应用数据目录不可用。")
    # The directory name is stable across display-name changes.
    return Path(local) / "AIJapaneseInterviewAssistant"


def validate_facts(facts):
    identifiers = set()
    if len(facts) > 100:
        raise ProfileError("最多保存 100 条资料。")
    for fact in facts:
        if not isinstance(fact.id, str) or not fact.id or fact.id in identifiers:
            raise ProfileError("资料标识无效。")
        identifiers.add(fact.id)
        if fact.category not in CATEGORIES:
            raise ProfileError("资料类别无效。")
        for text in (fact.ja, fact.zh):
            if not isinstance(text, str) or not text.strip() or len(text) > 240:
                raise ProfileError("每条资料须同时填写日语和中文，各限 240 字。")
        if len(fact.tags) > 10 or any(not isinstance(tag, str) or len(tag) > 40 for tag in fact.tags):
            raise ProfileError("每条资料最多 10 个关键词，每个限 40 字。")


class ProfileStore:
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else app_directory() / "profile.json"

    def load(self):
        try:
            with self.path.open(encoding="utf-8") as file:
                payload = json.loads(file.read(1_000_000))
            if payload["version"] != 1 or not isinstance(payload["facts"], list):
                raise ValueError
            facts = tuple(Fact(
                row["id"], row["category"], row["ja"], row["zh"], tuple(row.get("tags", ())),
            ) for row in payload["facts"])
            validate_facts(facts)
            return facts
        except FileNotFoundError:
            return ()
        except (KeyError, ValueError, TypeError, ProfileError) as exc:
            raise ProfileError("资料文件损坏或版本不受支持，原文件已保留。") from exc
        except OSError as exc:
            raise ProfileError("无法读取本地资料文件。") from exc

    def save(self, facts):
        validate_facts(facts)
        temporary = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                   prefix=".profile-", suffix=".tmp", delete=False) as file:
                temporary = Path(file.name)
                json.dump({"version": 1, "facts": [asdict(fact) for fact in facts]},
                          file, ensure_ascii=False, indent=2)
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            temporary.replace(self.path)
        except OSError as exc:
            raise ProfileError("无法保存本地资料。") from exc
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def select_facts(authorized, question, categories):
    normalized = question.casefold()
    ranked = []
    for fact in authorized:
        if fact.category in categories:
            matches = sum(bool(tag) and tag.casefold() in normalized for tag in fact.tags)
            if matches or not fact.tags:
                ranked.append((matches, fact))
    ranked.sort(key=lambda entry: -entry[0])
    return tuple(fact for _, fact in ranked[:2])
