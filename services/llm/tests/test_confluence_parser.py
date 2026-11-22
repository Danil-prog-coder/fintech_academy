from rag_service.ingest.confluence_parser import parse_confluence_html


def parse(html, **kwargs):
    return parse_confluence_html(
        html, title="БАРС-Офис", document_id="confluence:page:123",
        source_url="https://bars.atlassian.net/wiki/spaces/BARSER/pages/123/test",
        **kwargs,
    )


def test_heading_table_and_filter_symbols_remain_literal():
    doc = parse('<h2>Фильтры</h2><table><tr><th>Условие</th><th>Описание</th></tr>'
                '<tr><td>in A|B|C</td><td>&gt; &lt; = !=</td></tr></table>')
    assert doc.source_type == "confluence"
    assert doc.blocks[0].kind == "heading"
    assert doc.blocks[0].level == 2
    assert doc.blocks[1].rows == [["Условие", "Описание"], ["in A|B|C", "> < = !="]]


def test_storage_code_cdata_preserves_line_breaks_and_operators():
    doc = parse('<ac:structured-macro ac:name="code"><ac:parameter ac:name="language">text</ac:parameter>'
                '<ac:plain-text-body><![CDATA[!> 200\nin A|B|C]]></ac:plain-text-body>'
                '</ac:structured-macro>')
    assert len(doc.blocks) == 1
    assert doc.blocks[0].text == "!> 200\nin A|B|C"
    assert doc.blocks[0].meta["code"] is True


def test_link_is_preserved_but_scripts_are_not_content():
    doc = parse('<p>См. <a href="/wiki/spaces/BARSER/pages/456">Инструкцию</a></p>'
                '<script>invented policy</script><p><a href="javascript:alert(1)">текст</a></p>')
    assert "https://bars.atlassian.net/wiki/spaces/BARSER/pages/456" in doc.blocks[0].text
    assert "invented policy" not in str(doc.blocks)
    assert "javascript:" not in str(doc.blocks)


def test_images_require_validated_attachment_paths_no_remote_fetch():
    doc = parse('<p>Схема<ac:image><ri:attachment ri:filename="scheme.png" /></ac:image></p>'
                '<img src="https://external.example/private.png" />',
                image_paths={"scheme.png": "/validated/attachment.png"})
    images = [b for b in doc.blocks if b.kind == "image"]
    assert [b.image_path for b in images] == ["/validated/attachment.png"]
    assert any("unavailable" in w for w in doc.warnings)


def test_nested_list_does_not_duplicate_child_text():
    doc = parse('<ul><li>Родитель<ul><li>Ребёнок</li></ul></li></ul>')
    assert [(b.text, b.indent) for b in doc.blocks] == [("Родитель", 0), ("Ребёнок", 1)]


def test_merged_table_cells_are_explicitly_reported():
    doc = parse('<table><tr><td colspan="2">Общий заголовок</td></tr></table>')
    assert doc.blocks[0].meta["cell_spans"] == [[{"colspan": "2"}]]
    assert doc.warnings


def test_macro_parameters_are_not_published_business_content():
    doc = parse('<ac:structured-macro ac:name="include"><ac:parameter>SecretPage</ac:parameter>'
                '</ac:structured-macro><ac:structured-macro ac:name="note">'
                '<ac:parameter ac:name="colour">yellow</ac:parameter>'
                '<ac:rich-text-body><p>Важное примечание</p></ac:rich-text-body>'
                '</ac:structured-macro>')
    assert [b.text for b in doc.blocks] == ["Важное примечание"]
    assert any("include" in w for w in doc.warnings)
