import zipfile
from pathlib import Path

from jobagent.resumes.loader import docx_lines
from jobagent.resumes.tailor import _reorder, analyse_gaps, output_path, tailor_docx

SKILLS_XML = """<?xml version="1.0"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
 <w:body>
  <w:p><w:r><w:rPr><w:b/></w:rPr><w:t>SKILLS</w:t></w:r></w:p>
  <w:p>
   <w:r><w:rPr><w:b/></w:rPr><w:t>Data Engineering:</w:t></w:r>
   <w:r><w:t xml:space="preserve"> ETL, Star Schema, Batch Processing | </w:t></w:r>
   <w:r><w:rPr><w:b/></w:rPr><w:t>Technical:</w:t></w:r>
   <w:r><w:t xml:space="preserve"> Python, SQL, Docker</w:t></w:r>
  </w:p>
 </w:body>
</w:document>"""


def _make_docx(path: Path) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", SKILLS_XML)
    return path


def test_reorder_puts_priority_terms_first():
    assert _reorder(" ETL, Star Schema, Batch Processing", {"batch processing"}).strip().startswith(
        "Batch Processing"
    )


def test_reorder_preserves_surrounding_whitespace_and_separator():
    original = " ETL, Star Schema, Batch Processing | "
    result = _reorder(original, {"star schema"})
    assert result.startswith(" ")
    assert result.endswith(" | ")


def test_reorder_never_adds_or_drops_terms():
    original = " ETL, Star Schema, Batch Processing | "
    result = _reorder(original, {"star schema"})
    before = sorted(t.strip() for t in original.replace("|", "").split(",") if t.strip())
    after = sorted(t.strip() for t in result.replace("|", "").split(",") if t.strip())
    assert before == after


def test_tailoring_a_document_changes_order_but_not_content(tmp_path):
    src = _make_docx(tmp_path / "src.docx")
    dst = tmp_path / "out.docx"

    changed = tailor_docx(src, dst, {"docker", "batch processing"})

    assert changed > 0
    before = " ".join(docx_lines(src))
    after = " ".join(docx_lines(dst))
    assert before != after  # something moved
    # the safety property: identical set of terms in and out
    norm = lambda s: sorted(  # noqa: E731
        t.strip().lower() for t in s.replace("|", ",").replace(":", ",").split(",") if t.strip()
    )
    assert norm(before) == norm(after)


def test_bold_category_labels_are_never_rewritten(tmp_path):
    src = _make_docx(tmp_path / "src.docx")
    dst = tmp_path / "out.docx"
    tailor_docx(src, dst, {"docker"})
    text = " ".join(docx_lines(dst))
    assert "Data Engineering:" in text
    assert "Technical:" in text


def test_gaps_split_into_covered_missing_and_absent():
    report = analyse_gaps(
        job_text="We need Python, Airflow and Snowflake experience.",
        resume_text="Skills: Python, SQL",
        candidate_skills=["Python", "SQL", "Airflow"],
    )
    assert "python" in report.covered  # asked for, owned, on the resume
    assert "airflow" in report.missing  # asked for, owned, NOT on the resume
    assert "snowflake" in report.absent  # asked for, not owned - never added

def test_output_path_keeps_in_house_naming(tmp_path):
    source = Path("private/resumes/Andres_Torrado_Resume_D_Eng.docx")

    first = output_path(source, tmp_path)
    assert first.name == "Andres_Torrado_D_Eng.docx"

    # a copy still sitting there un-submitted must not be overwritten
    first.write_bytes(b"")
    assert output_path(source, tmp_path).name == "Andres_Torrado_D_Eng(1).docx"


def test_coverage_refuses_to_judge_a_title_only_posting():
    # LinkedIn alerts carry no description. "Data Analyst-Business
    # Intelligence" used to yield one covered term and a confident 100%.
    gaps = analyse_gaps(
        "Data Analyst-Business Intelligence",
        "SKILLS Business Intelligence, Power BI, SQL",
        ["business intelligence", "power bi", "sql"],
    )
    assert gaps.asked < 4
    assert gaps.coverage is None


def test_coverage_reports_once_the_posting_names_enough():
    gaps = analyse_gaps(
        "We need Python, SQL, Power BI and Airflow experience.",
        "SKILLS Python, SQL, Power BI",
        ["python", "sql", "power bi", "airflow"],
    )
    assert gaps.asked >= 4
    assert gaps.coverage == 100.0
