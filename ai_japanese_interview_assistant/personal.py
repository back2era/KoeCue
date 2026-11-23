"""Local storage, document import, and excerpt selection for interview context."""
from codecs import BOM_UTF16_BE, BOM_UTF16_LE
from contextlib import suppress
from dataclasses import asdict, dataclass, fields
from io import BytesIO
import json
import logging
import os
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
import unicodedata
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile
from zlib import error as ZlibError

from .personal_details import (
    EXPERIENCE_KINDS, LONG_FIELDS, MAX_DETAIL, MAX_RECORDS, PREFERENCE_OPTIONS, AnswerPreferences, Basics,
    Education, Experience, Target, filled, normalized,
)
from .profiles import ProfileError, app_directory


MAX_RESUME = 12_000
MAX_BACKGROUND = 4_000
MAX_SCENARIO = 1_000
MAX_FIELD = 120
MAX_EXCERPT = 240

_FIELD_LIMITS = {
    "background": ("个人背景", MAX_BACKGROUND),
    "resume": ("简历", MAX_RESUME),
    "company": ("目标公司", MAX_FIELD),
    "role": ("目标岗位", MAX_FIELD),
    "scenario": ("面试场景", MAX_SCENARIO),
}
_STORE_LIMIT = 512 * 1024
_IMPORT_LIMIT = 8 * 1_024 * 1_024
_STREAM_LIMIT = 2 * 1_024 * 1_024
_PDF_PAGE_LIMIT = 24
_INVALID_TEXT = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\ud800-\udfff]")

# Parser diagnostics can contain text taken from the resume.
_pdf_logger = logging.getLogger("pypdf")
_pdf_logger.addHandler(logging.NullHandler())
_pdf_logger.propagate = False


class PersonalError(ProfileError):
    """A personal context failure safe to show without file names or contents."""


@dataclass(frozen=True)
class PersonalInfo:
    background: str = ""
    resume: str = ""
    company: str = ""
    role: str = ""
    scenario: str = ""
    basics: Basics = Basics()
    education: tuple[Education, ...] = ()
    targets: tuple[Target, ...] = ()
    active_target: int = 0
    experiences: tuple[Experience, ...] = ()
    preferences: AnswerPreferences = AnswerPreferences()

    def __bool__(self):
        return (any(getattr(self, field).strip() for field in _FIELD_LIMITS)
                or bool(self.education or self.targets or self.experiences) or filled(self.basics))

    @property
    def target_context(self):
        if self.targets:
            return {key: value for key, value in asdict(self.targets[self.active_target]).items() if value}
        return {key: getattr(self, key) for key in ("company", "role", "scenario") if getattr(self, key)}

    @property
    def has_evidence(self):
        return bool(self.background.strip() or self.resume.strip()
                    or self.education or self.experiences or filled(self.basics))


def _decode_profile(payload):
    version = payload["version"]
    data = dict(payload["personal"])
    if type(version) is not int or version not in (1, 2):
        raise ValueError
    if version == 2:
        for key, row_type in (("education", Education), ("experiences", Experience), ("targets", Target)):
            rows = data.get(key, [])
            if not isinstance(rows, list) or len(rows) > MAX_RECORDS:
                raise ValueError
            data[key] = tuple(row_type(**row) for row in rows)
        data["basics"] = Basics(**data.get("basics", {}))
        data["preferences"] = AnswerPreferences(**data.get("preferences", {}))
    return PersonalInfo(**data)


def _validate_personal(info):
    if not isinstance(info, PersonalInfo):
        raise PersonalError("个人资料格式无效。")
    for field, (label, limit) in _FIELD_LIMITS.items():
        value = getattr(info, field)
        if not isinstance(value, str) or _INVALID_TEXT.search(value):
            raise PersonalError(f"{label}含无效文本。")
        if len(value) > limit:
            raise PersonalError(f"{label}最多填写 {limit} 字。")
    for rows, row_type in ((info.education, Education), (info.experiences, Experience), (info.targets, Target)):
        if not isinstance(rows, tuple) or len(rows) > MAX_RECORDS or any(not isinstance(row, row_type) for row in rows):
            raise PersonalError(f"每类资料最多保存 {MAX_RECORDS} 条记录。")
    if (type(info.active_target) is not int or not 0 <= info.active_target < max(1, len(info.targets))
            or not isinstance(info.basics, Basics) or not isinstance(info.preferences, AnswerPreferences)):
        raise PersonalError("个人资料格式无效。")
    for row in (info.basics, *info.education, *info.experiences, *info.targets):
        for field in fields(row):
            name = field.name
            value = getattr(row, name)
            if name == "priority":
                if type(value) is not bool:
                    raise PersonalError("经历优先设置无效。")
                continue
            limit = MAX_DETAIL if name in LONG_FIELDS else MAX_FIELD
            if not isinstance(value, str) or len(value) > limit or _INVALID_TEXT.search(value):
                raise PersonalError(f"单个资料字段最多可填写 {limit} 字，请检查较长的内容。")
        if isinstance(row, Experience) and row.kind not in EXPERIENCE_KINDS:
            raise PersonalError("经历类型无效。")
    if info.basics.japanese_level not in PREFERENCE_OPTIONS["level"] or any(
        not isinstance(value, str) or value not in PREFERENCE_OPTIONS[key]
        for key, value in asdict(info.preferences).items()
    ):
        raise PersonalError("回答偏好或日语等级无效。")


class PersonalStore:
    def __init__(self, path=None):
        try:
            self.path = Path(path) if path is not None else app_directory() / "personal.json"
        except ProfileError as exc:
            raise PersonalError(str(exc)) from None

    def load(self) -> PersonalInfo:
        try:
            with self.path.open("rb") as file:
                raw = file.read(_STORE_LIMIT + 1)
            if len(raw) > _STORE_LIMIT:
                raise ValueError
            payload = json.loads(raw.decode("utf-8"))
            info = _decode_profile(payload)
            _validate_personal(info)
            return info
        except FileNotFoundError:
            return PersonalInfo()
        except (KeyError, ValueError, TypeError, RecursionError, PersonalError):
            raise PersonalError("本地个人资料文件损坏或版本不受支持，原文件已保留。") from None
        except OSError:
            raise PersonalError("无法读取本地个人资料。") from None

    def save(self, info: PersonalInfo) -> None:
        _validate_personal(info)
        temporary = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                   prefix=".personal-", suffix=".tmp", delete=False) as file:
                temporary = Path(file.name)
                json.dump({"version": 2, "personal": asdict(info)}, file, ensure_ascii=False, indent=2)
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            temporary.replace(self.path)
        except OSError:
            raise PersonalError("无法保存本地个人资料。") from None
        finally:
            if temporary is not None:
                with suppress(OSError):
                    temporary.unlink(missing_ok=True)


def import_resume(path: str | Path) -> str:
    path = Path(path)
    kind = path.suffix.lower()
    if kind not in {".txt", ".docx", ".pdf"}:
        raise PersonalError("请选择 PDF、DOCX 或 TXT 简历文件。")
    try:
        if path.drive.startswith("\\\\") or not path.is_file():
            raise OSError
        with path.open("rb") as file:
            raw = file.read(_IMPORT_LIMIT + 1)
    except OSError:
        raise PersonalError("无法读取本地简历文件。") from None
    if len(raw) > _IMPORT_LIMIT:
        raise PersonalError("简历文件不能超过 8 MB。")

    if kind == ".pdf":
        text = _read_pdf(raw)
    elif kind == ".docx":
        text = _read_docx(raw)
    else:
        try:
            encoding = "utf-16" if raw.startswith((BOM_UTF16_BE, BOM_UTF16_LE)) else "utf-8-sig"
            text = raw.decode(encoding)
        except UnicodeError:
            raise PersonalError("无法读取 TXT 文本，请使用 UTF-8 或带 BOM 的 UTF-16。") from None

    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        raise PersonalError("简历没有可复制的文本，请粘贴文字或选择带文字层的文件。")
    _validate_personal(PersonalInfo(resume=text))
    return text


class _DocumentTreeBuilder(ElementTree.TreeBuilder):
    def doctype(self, name, pubid, system):
        raise PersonalError("DOCX 简历包含不支持的文档类型声明。")


def _read_docx(raw):
    try:
        with ZipFile(BytesIO(raw)) as archive:
            part = archive.getinfo("word/document.xml")
            if part.file_size > _STREAM_LIMIT:
                raise PersonalError("DOCX 正文过大，请精简简历后再导入。")
            with archive.open(part) as document:
                xml = document.read(_STREAM_LIMIT + 1)
        if len(xml) > _STREAM_LIMIT:
            raise PersonalError("DOCX 正文过大，请精简简历后再导入。")
        root = ElementTree.fromstring(xml, parser=ElementTree.XMLParser(target=_DocumentTreeBuilder()))
    except (BadZipFile, ElementTree.ParseError, KeyError, RuntimeError, ValueError, OSError, ZlibError):
        raise PersonalError("无法读取 DOCX 简历，文件可能已损坏或加密。") from None

    namespace = root.tag.removesuffix("document")
    if namespace not in (
        "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}",
        "{http://purl.oclc.org/ooxml/wordprocessingml/main}",
    ):
        raise PersonalError("DOCX 简历缺少有效正文。")
    body = root.find(namespace + "body")
    if body is None:
        raise PersonalError("DOCX 简历缺少有效正文。")

    paragraph_tag, text_tag = namespace + "p", namespace + "t"
    separators = {namespace + "tab": "\t", namespace + "br": "\n", namespace + "cr": "\n"}
    paragraphs = []
    stack = [(body, None)]
    while stack:
        node, parts = stack.pop()
        if node.tag == paragraph_tag:
            parts = []
            paragraphs.append(parts)
        elif parts is not None:
            if node.tag == text_tag and node.text:
                parts.append(node.text)
            elif node.tag in separators:
                parts.append(separators[node.tag])
        stack.extend((child, parts) for child in reversed(node))
    return "\n".join("".join(parts) for parts in paragraphs)


def _read_pdf(raw):
    try:
        from pypdf import PdfReader, apply_configuration
    except ImportError:
        raise PersonalError("PDF 解析组件不可用，请安装应用依赖或粘贴简历文本。") from None

    try:
        with apply_configuration(
            maximum_declared_stream_length=_IMPORT_LIMIT,
            array_based_stream_maximum_output_length=_STREAM_LIMIT,
            lzw_maximum_output_length=_STREAM_LIMIT,
            run_length_maximum_output_length=_STREAM_LIMIT,
            zlib_maximum_output_length=_STREAM_LIMIT,
            zlib_maximum_recovery_input_length=0,
            brotli_maximum_output_length=_STREAM_LIMIT,
            stream_decoding_work_maximum_length=4 * _STREAM_LIMIT,
            stream_parsing_work_maximum_count=150_000,
            page_tree_maximum_entries=128,
            page_tree_maximum_depth=32,
            page_tree_maximum_page_entries=4_096,
            xform_maximum_invocations_per_extraction=128,
            jbig2dec_binary=None,
        ):
            with PdfReader(BytesIO(raw), strict=True) as reader:
                if reader.is_encrypted:
                    raise PersonalError("请先解锁 PDF，再导入简历。")
                if len(reader.pages) > _PDF_PAGE_LIMIT:
                    raise PersonalError(f"PDF 简历最多 {_PDF_PAGE_LIMIT} 页。")
                chunks = []
                size = 0
                for page in reader.pages:
                    text = page.extract_text().strip()
                    if text:
                        size += len(text) + bool(chunks)
                        if size > MAX_RESUME:
                            raise PersonalError(f"简历最多填写 {MAX_RESUME} 字。")
                        chunks.append(text)
                return "\n".join(chunks)
    except PersonalError:
        raise
    except Exception:
        raise PersonalError("无法读取 PDF 简历，请检查文件或粘贴可复制的文本。") from None


_CATEGORY_TERMS = {
    "education": ("education", "studied", "university", "college", "degree", "major", "大学", "学歴", "学历",
                  "學歷", "毕业", "畢業", "卒業", "専攻", "专业", "專業", "学位", "学部", "学校", "學校"),
    "skill": ("skill", "skills", "proficient", "certified", "certification", "スキル", "技術", "技术", "技能",
              "资格", "資格", "熟练", "熟練", "擅长", "得意", "编程", "プログラミング"),
    "experience": ("experience", "employment", "worked", "internship", "team", "職歴", "履歴", "経験", "经历",
                   "經歷", "实习", "實習", "インターン", "担当", "负责", "負責", "在职", "在職", "勤務", "团队", "チーム"),
    "project": ("project", "projects", "developed", "implemented", "designed", "built", "プロジェクト", "開発", "开发",
                "项目", "項目", "專案", "专案", "研究", "设计", "設計", "制作", "製作", "実装", "实现", "實現"),
    "target": ("career", "goal", "motivation", "application", "志望", "応募", "应聘", "應聘", "目标", "目標",
               "岗位", "職種", "职位", "職位", "志向", "动机", "動機"),
}
_SECTION_TITLES = {
    title: category
    for category, titles in {
        "education": ("education", "educational background", "学歴", "学历", "學歷", "教育背景", "教育经历", "教育經歷", "学业经历", "academic background", "education background"),
        "skill": ("skills", "technical skills", "スキル", "技術スキル", "技能", "专业技能", "專業技能"),
        "experience": ("experience", "work experience", "professional experience", "職歴", "職務経歴", "工作经历",
                       "工作經歷", "实习经历", "實習經歷"),
        "project": ("projects", "personal projects", "プロジェクト", "プロジェクト経験", "项目经历", "項目經歷",
                    "项目经验", "專案經驗", "项目与实习", "项目与实习经历", "research projects"),
        "target": ("career objective", "objective", "志望動機", "求职意向", "求職意向"),
        "private": ("contact", "contact information", "personal information", "連絡先", "個人情報",
                    "联系方式", "聯絡方式", "个人信息", "個人資訊"),
        None: ("profile", "summary", "professional summary", "about me", "interests", "概要", "自己紹介",
               "自己pr", "自我介绍", "个人简介", "個人簡介"),
    }.items()
    for title in titles
}
_SUBJECT_TERMS = (
    ("power supply", "power electronics", "flyback", "电源", "電源", "反激", "フライバック"),
    ("medical", "medicine", "cardiomyopathy", "医学", "医疗", "醫療", "医療", "心肌病"),
    ("radio", "wireless", "無線", "无线"),
    ("measurement", "measured", "測定", "计测", "測量", "测量", "計測", "測試"),
    ("signal", "signals", "信号", "訊號"),
    ("circuit", "circuits", "回路", "电路", "電路"),
    ("data analysis", "analytics", "データ分析", "数据分析", "數據分析"),
    ("database", "databases", "データベース", "数据库", "資料庫"),
    ("quality", "品質", "质量", "品質管理"),
    ("teamwork", "collaboration", "チームワーク", "团队合作", "團隊合作", "协作", "協作"),
    ("leadership", "leader", "リーダー", "领导", "領導", "带领", "率いた"),
)
_ENGLISH_WORD = re.compile(r"[a-z][a-z0-9+#.\-]*")
_HAN = re.compile(r"[\u3400-\u9fff]{2,}")
_COMMON_WORDS = set(
    "a about am an and are as at be been by can could describe did do does for from give had has have how i if in is "
    "it its me my of on or our please say tell than that the their them these they this to us use used uses using was "
    "we were what when where which who why will with would you your".split()
)
_COMMON_HAN = {
    "介紹", "介绍", "自己", "何故", "請問", "请问", "貴方", "如何", "可以", "是否", "告訴", "告诉",
    "面接", "面试", "説明", "说明", "具体", "例子", "认为", "認為", "哪些", "做过", "做過",
}
_GENERIC_TOPIC_WORDS = {
    "between", "compare", "compared", "difference", "differences", "different", "example", "interview",
    "question", "questions", "project", "projects", "role", "technical", "vs",
}
_EXCERPT_BREAKS = re.compile(r"(?<=[。！？!?])\s*|(?<=\.)\s+")
_YEAR_MONTH = r"(?:19|20)\d{2}(?:[-./](?:0?[1-9]|1[0-2])\b|年(?:\d{1,2}月)?)?"
RESUME_DATE_RANGE = re.compile(rf"(?<!\d){_YEAR_MONTH}\s*[-–—~～至]\s*{_YEAR_MONTH}(?!\d)")
_CONTACT_DETAIL = re.compile(
    r"@\S+\.\S+|(?<!\d)\+?\d(?:[ ()\-.]*\d){9,}(?!\d)"
    r"|^\s*(?:address|e-?mail|phone|mobile|tel|住所|地址|電話|电话|連絡先|联系方式)\s*[:：]",
    re.IGNORECASE,
)


def _matches(term, text, words):
    return term in words if term.isascii() and " " not in term else term in text


def _words(text):
    return {word.rstrip(".-") for word in _ENGLISH_WORD.findall(text)}


def _han_pairs(text):
    return {part[i:i + 2] for part in _HAN.findall(text) for i in range(len(part) - 1)}


def _topic_words(text):
    return {word for word in _words(text) - _COMMON_WORDS - _GENERIC_TOPIC_WORDS if len(word) >= 2}


def _subjects_in(text, words):
    return [terms for terms in _SUBJECT_TERMS if any(_matches(term, text, words) for term in terms)]


def has_topic_cues(question):
    """Identify names, abbreviations or subject vocabulary in the question."""
    question = unicodedata.normalize("NFKC", question).casefold()
    words = _topic_words(question)
    return bool(words or _subjects_in(question, words))


def resume_section(title):
    title = normalized(title).strip(" \t#*•・[]【】:–—-")
    return _SECTION_TITLES.get(title, "")


def has_contact_detail(text):
    return bool(_CONTACT_DETAIL.search(RESUME_DATE_RANGE.sub(" ", normalized(text))))


def _excerpt_candidates(source):
    section = None
    lines_left = 0
    for line in source.splitlines():
        normalized = unicodedata.normalize("NFKC", line).casefold()
        heading = resume_section(line)
        if heading != "":
            section = heading
            lines_left = 3
            continue
        if section == "private" or not normalized.strip():
            continue
        if not has_contact_detail(line):
            for sentence in _EXCERPT_BREAKS.split(line):
                excerpt = sentence.strip()
                if excerpt and len(excerpt) <= MAX_EXCERPT:
                    yield excerpt, section if lines_left else None
        lines_left = max(0, lines_left - 1)


_EDUCATION_REQUEST = re.compile(
    r"自己紹介(?:を)?(?:お願い|して|お聞かせ)|学歴|専攻|簡単に自己紹介"
    r"|(?:自我介绍|自我介紹)|学历|學歷|毕业于哪|畢業於哪|(?:哪个|哪所|哪間)(?:学校|學校|大学|大學|学院|學院)"
    r"|你的.{0,8}(?:专业|專業)|tell me (?:a little )?about yourself|introduce yourself"
    r"|your (?:school|college|university|education|educational background|major)|what did you (?:study|major in)",
    re.IGNORECASE,
)
_SCHOOL = re.compile(r"大学|大學|学院|學院|学校|學校|高専|\b(?:university|college|institute of technology|school)\b")
_MAJOR = re.compile(
    r"専攻|专业|專業|学科|学部|\b(?:major|department|field of study)\b"
    r"|(?:工程|工学|科学|技术|engineering|informatics|science)(?:[\s（(]|$)"
)


def asks_about_education(question):
    return bool(_EDUCATION_REQUEST.search(unicodedata.normalize("NFKC", question)))


def _education_fields(text, section):
    fields = set()
    if _SCHOOL.search(text):
        fields.add("school")
    if _MAJOR.search(text) and (section == "education" or not fields or re.search(r"専攻|专业|專業|学科|工程|工学", text)):
        fields.add("major")
    return fields


def select_excerpts(info: PersonalInfo, categories, question: str, *, topic_only=False, education_first=False) -> tuple[str, ...]:
    """Select at most two relevant exact slices of the stored background or resume."""
    categories = set(categories)
    category_terms = {term for category in categories for term in _CATEGORY_TERMS.get(category, ())}
    if not category_terms and not topic_only:
        return ()
    question = unicodedata.normalize("NFKC", question).casefold()
    question_words = _topic_words(question) if topic_only else _words(question) - _COMMON_WORDS
    question_han = set() if topic_only else _han_pairs(question) - _COMMON_HAN
    subjects = _subjects_in(question, question_words)
    if topic_only and not (question_words or subjects):
        return ()
    # An expressly named subject takes precedence over the saved interview role.
    scope = subjects
    if topic_only and not scope:
        role = unicodedata.normalize("NFKC", f"{info.role}\n{info.scenario}").casefold()
        scope = _subjects_in(role, _words(role))

    ranked = {}
    scoped = {}
    education = {}
    for source in (info.background[:MAX_BACKGROUND], info.resume[:MAX_RESUME]):
        for excerpt, section in _excerpt_candidates(source):
            normalized = unicodedata.normalize("NFKC", excerpt).casefold()
            words = _words(normalized)
            category_match = section in categories or any(_matches(term, normalized, words) for term in category_terms)
            subject_matches = sum(any(_matches(term, normalized, words) for term in terms) for terms in subjects)
            overlap = len(words & question_words) + len(_han_pairs(normalized) & question_han)
            score = int(category_match) + 3 * subject_matches + 2 * overlap
            if education_first and not topic_only and (section == "education" or category_match):
                fields = _education_fields(normalized, section)
                if fields:
                    education[excerpt] = fields
                    score += 8 * len(fields) + 2 * (section == "education")
            if score:
                ranked[excerpt] = max(score, ranked.get(excerpt, 0))
                if topic_only and any(any(_matches(term, normalized, words) for term in terms) for terms in scope):
                    scoped[excerpt] = ranked[excerpt]
    results = scoped or ranked
    ordered = sorted(results, key=results.get, reverse=True)
    if education:
        first = next(excerpt for excerpt in ordered if excerpt in education)
        ordered.remove(first)
        missing = {"school", "major"} - education[first]
        second = next((excerpt for excerpt in ordered if education.get(excerpt, set()) & missing), None)
        if second:
            return first, second
        ordered.insert(0, first)
    return tuple(ordered[:2])
