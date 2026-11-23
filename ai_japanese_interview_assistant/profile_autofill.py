"""Pull recognizable fields from local résumé text, preserving uncertain lines."""
from dataclasses import asdict, replace
import re

from .personal import MAX_FIELD, RESUME_DATE_RANGE, PersonalInfo, has_contact_detail, resume_section
from .personal_details import LONG_FIELDS, MAX_DETAIL, MAX_RECORDS, Basics, Education, Experience, Target, filled, normalized


def aliases(**mapping):
    return {label: key for key, labels in mapping.items() for label in labels}


_BASIC_FIELDS = aliases(
    name=("姓名", "氏名", "名前", "name", "full name"),
    reading=("日语读音", "日語讀音", "假名", "フリガナ", "ふりがな", "name reading"),
    japanese_level=("日语水平", "日语等级", "日語程度", "日本語レベル", "jlpt", "japanese level"),
    languages=("其他语言", "其他语言能力", "語学", "語学力", "languages", "language skills"),
)
_EDUCATION_FIELDS = aliases(
    school=("学校", "學校", "学校名", "院校", "大学", "大学名", "school", "university", "college"),
    major=("专业", "專業", "専攻", "学科", "major", "field of study"),
    degree=("学历", "學歷", "学位", "學位", "学歴区分", "degree"),
    graduation=("毕业时间", "畢業時間", "毕业日期", "卒業年月", "卒業予定", "graduation", "graduation date"),
)
_TARGET_FIELDS = aliases(
    role=("求职意向", "求職意向", "应聘岗位", "目标岗位", "志望職種", "target role", "desired position"),
    company=("目标公司", "应聘公司", "応募先", "志望企業", "target company"),
    industry=("目标行业", "行业", "業界", "industry"),
    location=("工作地点", "勤務地", "location"),
    motivation=("求职动机", "应聘动机", "志望動機", "motivation"),
    requirements=("岗位要求", "職務要件", "requirements"),
    scenario=("面试场景", "面接場面", "interview context"),
)
_EXPERIENCE_FIELDS = aliases(
    title=("项目名称", "項目名称", "项目名", "プロジェクト名", "project", "project name", "岗位", "職種", "role", "title"),
    organization=("公司", "单位", "团队", "会社", "所属", "company", "organization"),
    period=("时间", "起止时间", "实习时间", "期間", "period", "dates"),
    background=("项目背景", "背景", "background", "overview"),
    responsibilities=("主要职责", "个人职责", "职责", "担当", "担当業務", "responsibilities", "my role"),
    tools=("使用工具", "工具", "使用技术", "技术栈", "使用技術", "開発環境", "technical skills", "tools", "technologies"),
    challenge=("遇到的问题", "问题", "挑战", "課題", "challenge", "problem"),
    actions=("解决过程", "解决方法", "行动", "対策", "解決策", "actions", "solution"),
    result=("团队成果", "项目结果", "结果", "成果", "团队结果", "チームの成果", "結果", "team result", "result", "outcome"),
    learning=("收获", "个人收获", "学び", "lessons", "learning"),
)
_KEY_VALUE = re.compile(r"^([^:：]{1,32})[:：]\s*(.+)$")
_JLPT = re.compile(r"(?<![a-z0-9])N[1-5](?![a-z0-9])", re.IGNORECASE)
_SCHOOL_NAME = re.compile(
    r"^(.+?(?:大学|大學|学院|學院|学校|學校|高専))(?=\s|$)"
    r"|^(.+?(?:university|college|institute of technology))(?=\s{2,}|$)", re.IGNORECASE,
)
_NUMBERED = re.compile(r"^[0-9]{1,2}[.)、]\s*")
_BULLET = re.compile(r"^[-•▪●*・]\s*")
_COLUMNS = re.compile(r"([ \t]{2,}|\t|[|｜])")
_KNOWN_LABELS = {*_BASIC_FIELDS, *_EDUCATION_FIELDS, *_TARGET_FIELDS, *_EXPERIENCE_FIELDS}


def _form_lines(text):
    for line in text.splitlines():
        parts = _COLUMNS.split(line)
        current = parts[0]
        for gap, fragment in zip(parts[1::2], parts[2::2]):
            entry = _KEY_VALUE.match(fragment.strip())
            if entry and normalized(entry[1]) in _KNOWN_LABELS:
                yield current
                current = fragment
            else:
                current += gap + fragment
        yield current


def _add(fields, key, value):
    limit = MAX_DETAIL if key in LONG_FIELDS else MAX_FIELD
    combined = "\n".join(part for part in (fields.get(key, ""), value.strip()) if part)
    if len(combined) <= limit:
        fields[key] = combined


def _education_line(line, fields):
    dates = RESUME_DATE_RANGE.search(line)
    body = (line[:dates.start()] + " " + line[dates.end():]).strip(" \t|｜") if dates else line
    columns = [part.strip() for part in re.split(r"\s{2,}|\t|[|｜]", body) if part.strip()]
    school = _SCHOOL_NAME.match(body)
    if not school and columns:
        school = _SCHOOL_NAME.match(columns[0])
    if school and school.end() <= MAX_FIELD:
        fields["school"] = school[0].strip()
        rest = body[school.end():].strip(" \t|｜·")
        degree = re.search(r"(?<![A-Za-z])(?:本科|硕士|碩士|博士|大专|学士|学部|修士|bachelor|master|phd)(?![A-Za-z])",
                           rest, re.IGNORECASE)
        if degree:
            fields["degree"] = degree[0]
            rest = (rest[:degree.start()] + rest[degree.end():]).strip(" \t|｜·()（）")
        if rest and len(rest) <= MAX_FIELD:
            fields["major"] = rest
    if dates:
        # A range describes study dates. The user can add an explicit graduation date.
        fields.setdefault("graduation", dates[0])
    return bool(school)


def organize_resume(text):
    """Produce editable suggestions from recognized labels and section headings."""
    basics, target = {}, {}
    sections = {"education": [], "experience": []}
    current = {}
    section = ""
    kind = "project"

    def flush():
        if section in sections and current:
            row = Education(**current) if section == "education" else Experience(kind=kind, **current)
            if filled(row) and len(sections[section]) < MAX_RECORDS:
                sections[section].append(row)
        current.clear()

    for source in _form_lines(text):
        line = source.strip()
        if not line or has_contact_detail(line):
            continue
        heading = resume_section(line)
        if heading != "":
            flush()
            header = normalized(line)
            kind = "project"
            if heading == "experience":
                internship = any(term in header for term in ("实习", "實習", "インターン", "internship"))
                kind = "internship" if internship else "employment"
            section = "experience" if heading in {"experience", "project"} else heading
            continue

        pair = _KEY_VALUE.match(_BULLET.sub("", line))
        key, value = (normalized(pair[1]), " ".join(pair[2].split())) if pair else ("", "")
        basic_key = _BASIC_FIELDS.get(key)
        if basic_key:
            if basic_key == "japanese_level":
                recognized = _JLPT.search(normalized(value))
                if recognized:
                    basics.setdefault(basic_key, recognized[0].upper())
            elif len(value) <= MAX_FIELD:
                basics.setdefault(basic_key, value)
            continue
        if section == "private":
            continue
        if key in _TARGET_FIELDS:
            _add(target, _TARGET_FIELDS[key], value)
            continue
        if section == "education" or key in _EDUCATION_FIELDS and section != "experience":
            section = "education"
            if key in _EDUCATION_FIELDS:
                field = _EDUCATION_FIELDS[key]
                if field == "school" and "school" in current:
                    flush()
                _add(current, field, value)
            else:
                proposed = {}
                if _education_line(line, proposed):
                    if "school" in current:
                        flush()
                    current.update(proposed)
            continue
        if section != "experience":
            continue

        field = _EXPERIENCE_FIELDS.get(key)
        if field:
            if field == "title" and "title" in current:
                flush()
            # Keep attribution labels such as “团队成果” in the imported text.
            _add(current, field, f"{pair[1].strip()}：{value}" if field == "result" else value)
        elif (not _BULLET.match(line) and len(line) <= MAX_FIELD
              and (not current or _NUMBERED.match(line) or RESUME_DATE_RANGE.match(line))):
            if current:
                flush()
            dates = RESUME_DATE_RANGE.search(line)
            title = line
            if dates:
                current["period"] = dates[0]
                title = line[:dates.start()] + " " + line[dates.end():]
            _add(current, "title", _NUMBERED.sub("", title.strip(" \t|｜")))
        else:
            _add(current, "notes", line)

    flush()
    return PersonalInfo(
        resume=text, basics=Basics(**basics), education=tuple(sections["education"]),
        targets=(Target(**target),) if target else (), experiences=tuple(sections["experience"]),
    )


def _fill_empty(current, imported):
    return replace(current, **{
        key: value for key, value in asdict(imported).items() if value and not getattr(current, key)
    })


def _merge_records(existing, imported, keys, distinguish=()):
    combined = list(existing)
    for item in imported:
        identifiers = {key: normalized(getattr(item, key)) for key in keys if getattr(item, key)}
        for index, old in enumerate(combined):
            shared = {key: normalized(getattr(old, key)) for key in identifiers if getattr(old, key)}
            matching = shared and all(identifiers[key] == text for key, text in shared.items())
            conflict = any(getattr(old, key) and getattr(item, key)
                           and normalized(getattr(old, key)) != normalized(getattr(item, key)) for key in distinguish)
            if matching and not conflict:
                combined[index] = _fill_empty(old, item)
                break
        else:
            if len(combined) < MAX_RECORDS:
                combined.append(item)
    return tuple(combined)


def merge_resume(current, imported):
    """Fill blank fields and add new rows, retaining existing edits."""
    return replace(
        current, resume=imported.resume, basics=_fill_empty(current.basics, imported.basics),
        education=_merge_records(current.education, imported.education, ("school",), ("major", "degree")),
        targets=_merge_records(current.targets, imported.targets, ("company", "role")),
        experiences=_merge_records(current.experiences, imported.experiences, ("title", "organization"), ("period", "kind")),
    )
