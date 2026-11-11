import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from ai_japanese_interview_assistant.personal import (
    MAX_EXCERPT,
    MAX_RESUME,
    PersonalError,
    PersonalInfo,
    PersonalStore,
    import_resume,
    select_excerpts,
)


def test_personal_data_round_trips_separately_in_local_app_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    store = PersonalStore()
    assert store.path == tmp_path / "AIJapaneseInterviewAssistant" / "personal.json"
    assert not store.load()
    info = PersonalInfo("模拟背景", "テスト履歴書", "Example Ltd", "Engineer", "一次面接")
    store.save(info)
    assert json.loads(store.path.read_text(encoding="utf-8"))["version"] == 1
    assert PersonalStore().load() == info
    store.save(PersonalInfo())
    assert not store.load()


def test_personal_data_invalid_save_preserves_existing_file(tmp_path):
    store = PersonalStore(tmp_path / "personal.json")
    info = PersonalInfo(background="模拟背景")
    store.save(info)
    with pytest.raises(PersonalError, match="字"):
        store.save(PersonalInfo(resume="字" * (MAX_RESUME + 1)))
    assert store.load() == info
    assert list(tmp_path.iterdir()) == [store.path]


def test_personal_data_failed_replace_preserves_previous_copy(tmp_path, monkeypatch):
    store = PersonalStore(tmp_path / "personal.json")
    info = PersonalInfo(background="模拟背景")
    store.save(info)

    def fail_replace(*args):
        raise PermissionError

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(PersonalError, match="保存"):
        store.save(PersonalInfo(background="別の背景"))
    assert store.load() == info
    assert list(tmp_path.iterdir()) == [store.path]


def test_personal_data_corrupt_file_is_preserved(tmp_path):
    store = PersonalStore(tmp_path / "personal.json")
    store.path.write_text('{"version":2}', encoding="utf-8")
    with pytest.raises(PersonalError, match="损坏"):
        store.load()
    assert store.path.read_text(encoding="utf-8") == '{"version":2}'


@pytest.mark.parametrize("encoding", ("utf-8", "utf-8-sig", "utf-16"))
def test_import_multilingual_text(tmp_path, encoding):
    path = tmp_path / "synthetic.TXT"
    path.write_bytes("模拟项目\r\nプロジェクト\r\nSample project".encode(encoding))
    assert import_resume(path) == "模拟项目\nプロジェクト\nSample project"


@pytest.mark.parametrize("raw", (b"\x00\x00\x01\x02", b"\xff\xfe\xff"))
def test_import_rejects_binary_text(tmp_path, raw):
    path = tmp_path / "synthetic.txt"
    path.write_bytes(raw)
    with pytest.raises(PersonalError, match="文本"):
        import_resume(path)


def test_import_rejects_oversized_resume_instead_of_silently_truncating(tmp_path):
    path = tmp_path / "synthetic.txt"
    path.write_text("字" * (MAX_RESUME + 1), encoding="utf-8")
    with pytest.raises(PersonalError, match="字"):
        import_resume(path)


def test_import_docx_preserves_paragraphs_and_table_cells(tmp_path):
    path = tmp_path / "synthetic.docx"
    with ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", """<w:document
            xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
            <w:body><w:p><w:r><w:t>模拟</w:t></w:r><w:r><w:t>项目</w:t></w:r></w:p>
            <w:tbl><w:tr><w:tc><w:p><w:r><w:t>技能</w:t></w:r></w:p></w:tc>
            <w:tc><w:p><w:r><w:t>Python</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
            </w:body></w:document>""")
    assert import_resume(path) == "模拟项目\n技能\nPython"


def test_import_docx_does_not_duplicate_text_inside_text_box(tmp_path):
    path = tmp_path / "synthetic.docx"
    with ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", """<w:document
            xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
            <w:body><w:p><w:r><w:t>Example</w:t><w:pict><w:txbxContent>
            <w:p><w:r><w:t>Text box</w:t></w:r></w:p></w:txbxContent></w:pict>
            </w:r></w:p></w:body></w:document>""")
    assert import_resume(path) == "Example\nText box"


def test_import_docx_rejects_entity_declaration_even_with_utf16(tmp_path):
    path = tmp_path / "synthetic.docx"
    with ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", """<?xml version="1.0" encoding="UTF-16"?>
            <!DOCTYPE w:document [<!ENTITY synthetic "Synthetic">]>
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
            <w:body><w:p><w:r><w:t>&synthetic;</w:t></w:r></w:p></w:body></w:document>""".encode("utf-16"))
    with pytest.raises(PersonalError, match="DOCX"):
        import_resume(path)


def test_import_docx_limits_uncompressed_document_size(tmp_path):
    path = tmp_path / "synthetic.docx"
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", b" " * (3 * 1024 * 1024))
    with pytest.raises(PersonalError, match="正文过大"):
        import_resume(path)


def test_import_pdf_extracts_selectable_text(tmp_path):
    path = tmp_path / "synthetic.pdf"
    writer = PdfWriter()
    page = writer.add_blank_page(200, 200)
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({
            NameObject("/F1"): DictionaryObject({
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }),
        }),
    })
    content = DecodedStreamObject()
    content.set_data(b"BT /F1 10 Tf 20 100 Td (Sample project) Tj ET")
    page.replace_contents(content)
    writer.write(path)
    assert import_resume(path) == "Sample project"


def test_import_pdf_reports_missing_selectable_text(tmp_path):
    path = tmp_path / "synthetic.pdf"
    writer = PdfWriter()
    writer.add_blank_page(200, 200)
    writer.write(path)
    with pytest.raises(PersonalError, match="可复制"):
        import_resume(path)


def test_import_pdf_reports_encryption_without_asking_for_credentials(tmp_path):
    path = tmp_path / "synthetic.pdf"
    writer = PdfWriter()
    writer.add_blank_page(200, 200)
    writer.encrypt("sample-password")
    writer.write(path)
    with pytest.raises(PersonalError, match="解锁"):
        import_resume(path)


def test_japanese_question_ranks_chinese_and_english_projects():
    info = PersonalInfo(
        background="我在某大学学习工学。",
        resume="开发了模拟无线通信项目。\nProject: Implemented a Python dashboard.\nSkills: SQL and testing.",
    )
    assert select_excerpts(info, ("project",), "プロジェクトで Python を使いましたか？") == (
        "Project: Implemented a Python dashboard.", "开发了模拟无线通信项目。",
    )


def test_excerpts_use_exact_source_text_and_omit_unrelated_contact_lines():
    relevant = "Project: I developed a sensor test tool."
    resume = (
        "Example University\nProject contact: test＠example．invalid\n"
        + "在该项目中我没有参与" + "字" * 500 + "负责项目。\n" + relevant
    )
    excerpts = select_excerpts(PersonalInfo(resume=resume), ("project",), "プロジェクトについて教えてください。")
    assert excerpts == (relevant,)
    assert len(relevant) <= MAX_EXCERPT and relevant in resume


def test_excerpts_need_relevant_material_and_categories():
    info = PersonalInfo(background="Example University", company="Example Corp")
    assert select_excerpts(info, ("project",), "プロジェクトは何ですか？") == ()
    assert select_excerpts(info, (), "大学について教えてください。") == ()


def test_ordinary_question_words_do_not_make_unrelated_lines_relevant():
    info = PersonalInfo(background="I am a university graduate.")
    assert select_excerpts(info, ("project",), "Can you tell me about a project?") == ()


def test_cross_language_subject_matches_without_a_category_heading():
    info = PersonalInfo(resume="I measured radio signals.\nPrivate fixture marker.")
    question = "無線信号の測定をしたプロジェクトについて教えてください。"
    assert select_excerpts(info, ("project",), question) == ("I measured radio signals.",)


def test_section_heading_gives_skill_context_to_an_exact_following_line():
    info = PersonalInfo(resume="Skills\nPython, C++, MATLAB\n教育背景\n模拟大学毕业。\nContact\nPrivate marker")
    assert select_excerpts(info, ("skill",), "得意なプログラミング言語は何ですか。") == (
        "Python, C++, MATLAB",
    )


def test_contact_section_never_supplies_an_excerpt_even_when_question_terms_match():
    info = PersonalInfo(resume=(
        "联系方式\n会社の住所 東京都サンプル区\n補足欄\n会社の建物 1004\n\n"
        "職歴\n会社でテスト作業を担当しました。"
    ))
    assert select_excerpts(info, ("experience",), "会社の経験を教えてください。") == (
        "会社でテスト作業を担当しました。",
    )
