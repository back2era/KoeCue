"""Select a few relevant fields from the saved profile for a single answer."""
import re

from .personal import _COMMON_HAN, _han_pairs, _subjects_in, _topic_words, _words, has_contact_detail
from .personal_details import EXPERIENCE_KINDS, normalized


_MAX_EVIDENCE_CHARS = 1_050
_GENERIC_TERMS = set(
    "项目 項目 专案 專案 经历 經歷 经验 経験 実績 负责 負責 职责 職責 担当 工具 使用 结果 結果 "
    "成果 团队 團隊 实习 實習 工作 介绍 介紹 internship intern experience worked work tool tools "
    "team result results responsibility responsibilities detail details project projects actually".split()
)
_PERSONAL = re.compile(
    r"你的|您的|你在|您在|你是|你用|您用|你做|您做|你负责|你參與|你参与|你遇到|你怎么|你如何"
    r"|ご自身|あなた|担当した|携わった|経験した|実際に|取り組んだ|どのように.*しました"
    r"|\b(?:your|did you|one of your|you (?:worked|built|led|designed|handled|used|tested))\b", re.IGNORECASE,
)
_EXPERIENCE = re.compile(
    r"项目|項目|專案|专案|经历|經歷|经验|経験|实习|實習|プロジェクト|インターン|担当"
    r"|\b(?:projects?|internship|experience|role)\b", re.IGNORECASE,
)
_GENERIC = re.compile(
    r"(?:一个|一段|一項|一项|一次).{0,8}(?:项目|項目|经历|經歷|经验|経験|实习|實習)"
    r"|(?:项目|实习|實習|工作|職務|インターン)(?:经历|經歷|経験)(?:[。？！?]|$)"
    r"|(?:プロジェクト|インターン|経験)(?:について|を)(?:教えて|紹介)"
    r"|\b(?:an? example|one of your|an? internship|an? project|your work experience)\b", re.IGNORECASE,
)
_INTERNSHIP = re.compile(r"实习|實習|インターン|\binternship\b", re.IGNORECASE)
_EMPLOYMENT = re.compile(r"工作经历|工作經歷|職務経歴|\bwork experience\b", re.IGNORECASE)
_ORGANIZATION = re.compile(r"哪[家个間]|哪个公司|在哪儿|どの会社|どこで|\b(?:which employer|where did you work)\b", re.IGNORECASE)
_DURATION = re.compile(r"多久|多长时间|多長時間|どのくらい|期間|\bhow long\b", re.IGNORECASE)
_TOOLS = re.compile(r"工具|设备|設備|技术栈|技術スタック|ツール|測定器|機材|\b(?:tools?|equipment|stack)\b", re.IGNORECASE)
_RESULT = re.compile(r"结果|結果|成果|成效|收获|学び|\b(?:results?|outcome|impact|learned)\b", re.IGNORECASE)
_CHALLENGE = re.compile(r"困难|困難|难点|難点|解决|解決|挑战|挑戦|課題|\b(?:challenge|problem|solv\w*)\b", re.IGNORECASE)
_INTRO = re.compile(r"自我介绍|自我介紹|自己紹介|about yourself|introduce yourself", re.IGNORECASE)
_LANGUAGES = re.compile(r"语种|語種|语言能力|語学|日语|日語|日本語|jlpt|\b(?:language skills|japanese)\b", re.IGNORECASE)
_LABELS = {
    "background": "背景", "responsibilities": "我的职责", "tools": "使用技术或工具", "challenge": "遇到的问题",
    "actions": "我的解决过程", "result": "项目或团队结果（以原文归属为准）", "learning": "我的收获", "notes": "简历原文摘录",
}


_HYPOTHETICAL = re.compile(r"如果|假设|假設|あなたなら|としたら|\b(?:would you|if you|hypothetical)\b", re.IGNORECASE)


def asks_about_experience(question):
    return bool(not _HYPOTHETICAL.search(question) and _PERSONAL.search(question) and _EXPERIENCE.search(question))


def _terms(text):
    subjects = {terms[0] for terms in _subjects_in(text, _words(text))}
    return ((_topic_words(text) | _han_pairs(text) | subjects) - _COMMON_HAN) - _GENERIC_TERMS


def _safe(value):
    return "\n".join(line.strip() for line in value.splitlines() if line.strip() and not has_contact_detail(line))


def _format_evidence(pairs):
    lines = []
    length = 0
    for label, value in pairs:
        value = _safe(value)
        if value and length + len(label) + len(value) + 2 <= _MAX_EVIDENCE_CHARS:
            lines.append(f"{label}：{value}")
            length += len(lines[-1]) + 1
    return "\n".join(lines)


def select_experience(records, question, lookup, *, technical_only=False):
    """Rank current-topic and named matches before transcript history and priority."""
    allowed_kind = "internship" if _INTERNSHIP.search(question) else "employment" if _EMPLOYMENT.search(question) else ""
    current = normalized(question)
    previous = normalized(lookup)
    current_terms, past_terms = _terms(current), _terms(previous)
    fallback = not technical_only and bool(
        _GENERIC.search(question) or (allowed_kind and (_ORGANIZATION.search(question) or _DURATION.search(question)))
    )
    ranked = []
    for record in records:
        title = normalized(record.title)
        named = bool(title and title in current)
        if allowed_kind and record.kind != allowed_kind and not named:
            continue
        title_terms = _terms(title)
        body = normalized(" ".join(_safe(getattr(record, key)) for key in _LABELS))
        if not body:
            continue
        body_terms = _terms(body)
        rank = (
            len(title) if named else 0,
            len(current_terms & title_terms),
            len(title) if title and title in previous else 0,
            len(past_terms & title_terms),
            len(current_terms & body_terms), len(past_terms & body_terms),
        )
        if any(rank) or fallback:
            ranked.append(((*rank, record.priority), record))
    if not ranked:
        return ""
    _, record = max(ranked, key=lambda item: item[0])

    lead = [("经历", record.title), ("类型", EXPERIENCE_KINDS[record.kind])]
    if technical_only:
        order = ("tools", "background", "challenge", "notes")
    elif _TOOLS.search(question):
        order = ("tools", "responsibilities", "actions", "notes")
    elif _CHALLENGE.search(question):
        order = ("challenge", "actions", "responsibilities", "result", "learning", "notes")
    elif _RESULT.search(question):
        order = ("result", "responsibilities", "actions", "learning", "notes")
    elif _ORGANIZATION.search(question) or _DURATION.search(question):
        lead.extend((("单位或团队", record.organization), ("持续时间", record.period)))
        order = ("responsibilities", "notes")
    else:
        if fallback:
            lead.extend((("单位或团队", record.organization), ("持续时间", record.period)))
        order = ("responsibilities", "actions", "tools", "background", "challenge", "result", "notes")
    details = [(_LABELS[key], getattr(record, key)) for key in order if getattr(record, key)]
    evidence = _format_evidence(details[:5])
    if not evidence and not (_ORGANIZATION.search(question) or _DURATION.search(question)):
        return ""
    return _format_evidence([*lead, *details[:5]])


def education_evidence(records, question):
    if not records:
        return ""
    query = normalized(question)
    terms = _terms(query)
    record = max(records, key=lambda row: (
        len(_terms(normalized(f"{row.school} {row.major}")) & terms),
        bool(row.school) + bool(row.major),
    ))
    return _format_evidence((
        ("学校", record.school), ("专业", record.major), ("学历或学位", record.degree),
        ("就读或毕业时间（以填写内容为准）", record.graduation),
    ))


def introduction_evidence(basics, question):
    if not _INTRO.search(question):
        return ""
    return _format_evidence((("姓名", basics.name), ("姓名日语读音", basics.reading)))


def language_evidence(basics, question):
    if not _LANGUAGES.search(question):
        return ""
    return _format_evidence((("日语水平", basics.japanese_level), ("其他语言", basics.languages)))
