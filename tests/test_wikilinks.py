from docgraph.links import build_wikilink_index, extract_wikilinks, resolve_link, resolve_wikilink


def test_extract_strips_alias_heading_block_and_skips_code_and_attachments():
    body = (
        "See [[Note A]] and [[Note B|alias]], [[Note C#Section]], [[Note D^abc123]].\n"
        "Embedded note ![[Note E]] but not ![[diagram.png]] or ![[paper.pdf]].\n"
        "`[[Inline Code]]`\n```\n[[Fenced]]\n```\n[[  ]]"
    )
    assert extract_wikilinks(body) == ["Note A", "Note B", "Note C", "Note D", "Note E"]


def test_resolve_by_case_insensitive_stem():
    idx = build_wikilink_index({"Projects/My Note.md", "Other.md"})
    assert resolve_wikilink("my note", idx) == "Projects/My Note.md"
    assert resolve_wikilink("My Note.md", idx) == "Projects/My Note.md"
    assert resolve_wikilink("Missing", idx) is None


def test_ambiguous_stem_resolves_only_to_unique_shallowest():
    idx = build_wikilink_index({"a/Topic.md", "Topic.md", "b/c/Topic.md"})
    assert resolve_wikilink("Topic", idx) == "Topic.md"
    tie = build_wikilink_index({"a/Topic.md", "b/Topic.md"})
    assert resolve_wikilink("Topic", tie) is None  # no edges beats wrong edges


def test_path_qualified_name_disambiguates_a_tie():
    idx = build_wikilink_index({"a/Topic.md", "b/Topic.md"})
    assert resolve_wikilink("b/Topic", idx) == "b/Topic.md"


def test_markdown_link_resolves_url_encoded_paths():
    assert resolve_link("x/Index.md", "My%20Note.md", {"x/My Note.md"}) == "x/My Note.md"
