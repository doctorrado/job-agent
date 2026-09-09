from jobagent.resumes.loader import parse_resume
from jobagent.resumes.select import build_weights, choose_resume

# Deliberately built from plain lines, not real .docx files: the actual
# resumes are gitignored personal documents, so tests must not depend on them.
DATA_ENG = [
    "Andres Torrado",
    "PROFESSIONAL SUMMARY",
    "Data Engineer building pipelines.",
    "EXPERIENCE",
    "Some role that should be ignored by the parser.",
    "SKILLS",
    "Data Engineering: ETL, Star Schema, Data Warehousing | Technical: Python, SQL, Docker"
    " | Languages: English, Spanish",
]
MANUFACTURING = [
    "Andres Torrado",
    "PROFESSIONAL SUMMARY",
    "Manufacturing analytics professional.",
    "SKILLS",
    "Operations: OEE, Downtime Analysis | Technical: Python, SQL | Languages: English, Spanish",
]


def _weights():
    return build_weights(
        [parse_resume("D_Eng", DATA_ENG), parse_resume("Manf", MANUFACTURING)]
    )


def test_parse_resume_reads_skills_and_summary():
    profile = parse_resume("D_Eng", DATA_ENG)
    assert "star schema" in profile.skills
    assert "python" in profile.skills
    assert profile.summary == "Data Engineer building pipelines."
    # languages say nothing about which resume fits
    assert "english" not in profile.skills
    # non-SKILLS sections are not scraped for terms
    assert not any("ignored" in s for s in profile.skills)


def test_terms_unique_to_one_resume_outweigh_shared_ones():
    weights = _weights()
    assert weights["D_Eng"]["star schema"] == 1.0  # only on D_Eng
    assert weights["D_Eng"]["python"] == 0.5  # on both


def test_chooses_the_resume_whose_vocabulary_the_posting_uses():
    choice = choose_resume(
        "We need someone for ETL work, star schema design and data warehousing.", _weights()
    )
    assert choice.best.resume == "D_Eng"
    assert "star schema" in choice.best.reasons


def test_html_job_descriptions_are_handled():
    escaped = "&lt;p&gt;Experience with &lt;b&gt;OEE&lt;/b&gt; and downtime analysis&lt;/p&gt;"
    choice = choose_resume(escaped, _weights())
    assert choice.best.resume == "Manf"


def test_a_posting_matching_nothing_is_reported_as_weak():
    choice = choose_resume("We are hiring a pastry chef for our bakery.", _weights())
    assert choice.is_weak


def test_close_scores_are_reported_as_ambiguous():
    # only shared terms appear, so both resumes score identically
    choice = choose_resume("Looking for Python and SQL skills.", _weights())
    assert choice.is_ambiguous
