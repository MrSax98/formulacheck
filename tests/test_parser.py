from formulacheck.parser import parse_text


def test_finds_single_and_multi_line_display_math() -> None:
    doc = parse_text("intro\n$$ a = b $$\n\n$$\nx^2 +\ny^2\n$$\n\\[ c = d \\]\n")
    assert [(e.line, e.tex) for e in doc.equations] == [
        (2, "a = b"),
        (4, "x^2 + y^2"),
        (8, "c = d"),
    ]


def test_math_inside_other_code_fences_is_ignored() -> None:
    doc = parse_text("```python\n$$ not math $$\n```\n$$ real $$\n")
    assert [e.tex for e in doc.equations] == ["real"]


def test_check_block_attaches_to_last_preceding_equation() -> None:
    text = "$$ f = 1 $$\n\n```check\nid: a\n```\n\n$$ g = 2 $$\n```check\nid: b\n```\n"
    doc = parse_text(text)
    assert [(b.line, b.equation.tex if b.equation else None) for b in doc.blocks] == [
        (3, "f = 1"),
        (8, "g = 2"),
    ]


def test_check_block_without_equation_is_kept() -> None:
    doc = parse_text("```check\nid: a\n```\n")
    assert len(doc.blocks) == 1 and doc.blocks[0].equation is None


def test_tilde_fences_and_longer_fences() -> None:
    doc = parse_text("````check\nid: a\n```\nstill inside\n````\n~~~check\nid: b\n~~~\n")
    assert [b.line for b in doc.blocks] == [1, 6]
    assert "still inside" in doc.blocks[0].raw


def test_unterminated_display_math_is_ignored() -> None:
    assert parse_text("$$\nnever closed\n").equations == []
