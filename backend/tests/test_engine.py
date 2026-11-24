import os
from pathlib import Path

import pytest

os.environ.setdefault("LATEX_ENGINE", "pdflatex")

from app.ats.score import score
from app.guard import check_revision
from app.latex.apply import apply_revisions, escape_latex
from app.latex.compile import UnsafeLatex, check_safe, compile_pdf
from app.latex.extract import extract_blocks, to_plain
from app.schemas import JDProfile, Revision, Skill

TEX = (Path(__file__).parent / "fixtures" / "jake_resume.tex").read_text()
JD = JDProfile(title="ML Intern", hard_skills=[
    Skill(name="PyTorch"), Skill(name="Computer Vision"), Skill(name="Kubernetes"),
    Skill(name="Docker", importance="nice")], keywords=["object detection"])


def test_extract_skips_skills_and_finds_bullets():
    blocks = extract_blocks(TEX)
    assert [b.kind for b in blocks] == ["summary", "bullet", "bullet", "bullet", "bullet"]
    assert all("skill" not in b.section.lower() for b in blocks)
    assert "12 room & 12 icon" in blocks[1].text
    assert "% keep" not in blocks[3].source


def test_to_plain_handles_escapes_and_macros():
    assert to_plain(r"\textbf{50\%} of \href{https://x.y}{site} \& \{x\}") == "50% of site & {x}"


def test_apply_is_byte_exact_outside_edited_spans_and_keeps_bold():
    blocks = extract_blocks(TEX)
    b = blocks[1]
    new = "Trained a multitask U-Net on CubiCasa5K for 12 room & 12 icon classes (0.747 mean IoU)"
    out = apply_revisions(TEX, blocks, {b.id: new})
    assert out[:b.start] == TEX[:b.start]
    assert out.endswith(TEX[b.end:])
    assert r"12 room \& 12 icon" in out and r"\textbf{0.747}" in out


def test_escape():
    assert escape_latex("C++ & 100% $5 #1 a_b") == r"C++ \& 100\% \$5 \#1 a\_b"


def test_compile_and_score_improves_after_edit():
    blocks = extract_blocks(TEX)
    before = compile_pdf(TEX)
    assert before.ok, before.log
    bullets = [b.text for b in blocks if b.kind == "bullet"]
    r1 = score(JD, before.pdf, bullets)
    assert 0 < r1.total <= 100
    assert "Kubernetes" in r1.missing
    b = blocks[2]
    new = "Built a YOLO11m-OBB object detection model for computer vision on FloorPlanCAD (18 classes, mAP50 about 0.87)"
    tex2 = apply_revisions(TEX, blocks, {b.id: new})
    after = compile_pdf(tex2)
    assert after.ok, after.log
    r2 = score(JD, after.pdf, [new if x.id == b.id else x.text for x in blocks if x.kind == "bullet"])
    assert r2.total > r1.total


def test_unsafe_latex_blocked():
    for bad in [r"\immediate\write18{rm -rf /}", r"\input{/etc/passwd}", r"\input{../../x}"]:
        with pytest.raises(UnsafeLatex):
            check_safe(TEX.replace(r"\begin{document}", r"\begin{document}" + bad))


@pytest.mark.parametrize("new,ok", [
    ("Trained a U-Net on CubiCasa5K reaching 0.747 mean IoU", True),
    ("Trained a U-Net on CubiCasa5K reaching 0.95 mean IoU", False),       # invented number
    ("Trained a U-Net on CubiCasa5K and deployed it on Kubernetes", False),  # skill not in resume
    ("Trained a U-Net with TensorRT on CubiCasa5K", False),                  # new tool
])
def test_guard(new, ok):
    blocks = extract_blocks(TEX)
    resume = "\n".join(b.text for b in blocks)
    why = check_revision(Revision(id="b02", new_text=new, reason=""), blocks[1].text, resume, JD)
    assert (why is None) == ok, why


def test_temp_storage_sweep_and_delete(tmp_path, monkeypatch):
    import time
    from app import storage
    monkeypatch.setattr(storage, "ROOT", tmp_path)
    storage.write("me", "jobA", "original.tex", "x")
    storage.write("me", "jobB", "original.tex", "y")
    old = time.time() - 7200
    for f in (tmp_path / "me" / "jobA").iterdir():
        import os; os.utime(f, (old, old))
    assert storage.sweep(ttl=3600) == 1
    assert storage.read("me", "jobA", "original.tex") is None
    assert storage.read("me", "jobB", "original.tex") == b"y"
    storage.delete("me", "jobB")
    assert not (tmp_path / "me" / "jobB").exists()


def test_every_block_can_be_replaced_and_compiles():
    """Replace every editable block of the real resume with text full of special characters."""
    for f in sorted((Path(__file__).parent / "fixtures").glob("*.tex")):
        tex = f.read_text()
        blocks = extract_blocks(tex)
        edits = {b.id: "Rewrote 50% of {this} & more_text #1 ~ ^ \\ done" for b in blocks}
        res = compile_pdf(apply_revisions(tex, blocks, edits))
        assert res.ok, res.log


def test_unicode_from_models_compiles():
    blocks = extract_blocks(TEX)
    weird = ("Trained a U‑Net — 0.747 IoU ≤ 1 × 2 → 3 “quoted” … "
             "café ‘x’ ₹ 40 000 μs \U0001F680 ​✓ 中")
    res = compile_pdf(apply_revisions(TEX, blocks, {b.id: weird for b in blocks}))
    assert res.ok, res.log


def test_titlesec_error_message_points_to_line():
    bad = TEX.replace(r"\section{Summary}", r"\section{Summary}\titlerule*{x}", 1)
    bad = bad.replace(r"\titlerule \vspace{-5pt}]", r"\titlerule*[1em] \vspace{-5pt}]")
    res = compile_pdf(bad)
    if not res.ok:
        assert "line" in res.log or "!" in res.log


def test_auto_repair_uppercase_titleformat():
    from app.latex.repair import uppercase_in_titleformat
    bad = (r"\documentclass{article}\usepackage{titlesec}"
           r"\titleformat{\section}{\large\bfseries\MakeUppercase}{}{0pt}{}[\titlerule]"
           "\n\\begin{document}\\section*{Summary}Text.\\end{document}")
    assert not compile_pdf(bad).ok
    fixed, _ = uppercase_in_titleformat(bad)
    assert r"{\large\bfseries}{}{0pt}{\MakeUppercase}[\titlerule]" in fixed
    assert compile_pdf(fixed).ok
