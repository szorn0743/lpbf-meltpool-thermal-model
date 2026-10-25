"""A minimal, deterministic .docx writer for the thesis tables and figures.

The document uses the thesis's own paragraph styles by ID ("TableTitle" above tables, "Figure" for the picture
paragraph, "Caption" below figures), so that pasted items keep their style and are collected by the thesis's List of
Tables (TOC \\t "Table Title" \\c "Table") and List of Figures (TOC \\t "Caption"). Caption numbers are SEQ fields with
cached values in document order. Fixed zip timestamps make the file byte-identical from build to build.
"""
from __future__ import annotations

import re
import struct
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

EMU_PER_IN = 914400
TEXT_WIDTH_IN = 6.25
TEXT_WIDTH_TWIPS = int(TEXT_WIDTH_IN * 1440)
ZIP_TIME = (2026, 1, 1, 0, 0, 0)

NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
      'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
      'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
      'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
      'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"')

STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Times New Roman" w:eastAsia="Times New Roman" w:hAnsi="Times New Roman" w:cs="Times New Roman"/><w:sz w:val="24"/><w:szCs w:val="24"/><w:lang w:val="en-US"/></w:rPr></w:rPrDefault><w:pPrDefault/></w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/><w:pPr><w:spacing w:line="360" w:lineRule="auto"/></w:pPr><w:rPr><w:sz w:val="24"/><w:szCs w:val="24"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/><w:spacing w:before="240" w:after="120"/><w:outlineLvl w:val="0"/></w:pPr><w:rPr><w:b/><w:sz w:val="28"/></w:rPr></w:style>
<w:style w:type="paragraph" w:customStyle="1" w:styleId="TableTitle"><w:name w:val="Table Title"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:pPr><w:keepNext/><w:keepLines/><w:spacing w:before="240" w:after="120" w:line="240" w:lineRule="auto"/></w:pPr><w:rPr><w:b/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Caption"><w:name w:val="caption"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepLines/><w:spacing w:after="360" w:line="240" w:lineRule="auto"/></w:pPr><w:rPr><w:b/><w:bCs/></w:rPr></w:style>
<w:style w:type="paragraph" w:customStyle="1" w:styleId="Figure"><w:name w:val="Figure"/><w:basedOn w:val="Normal"/><w:next w:val="Caption"/><w:pPr><w:keepNext/><w:spacing w:before="240" w:line="240" w:lineRule="auto"/><w:jc w:val="center"/></w:pPr></w:style>
<w:style w:type="paragraph" w:customStyle="1" w:styleId="TableText"><w:name w:val="Table Text"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:before="20" w:after="20" w:line="240" w:lineRule="auto"/></w:pPr><w:rPr><w:sz w:val="20"/><w:szCs w:val="20"/></w:rPr></w:style>
<w:style w:type="paragraph" w:customStyle="1" w:styleId="TableNote"><w:name w:val="Table Note"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:before="60" w:after="240" w:line="240" w:lineRule="auto"/></w:pPr><w:rPr><w:sz w:val="20"/><w:szCs w:val="20"/></w:rPr></w:style>
<w:style w:type="paragraph" w:customStyle="1" w:styleId="Placement"><w:name w:val="Placement"/><w:basedOn w:val="Normal"/><w:pPr><w:keepNext/><w:pBdr><w:top w:val="single" w:sz="4" w:space="4" w:color="BFBFBF"/></w:pBdr><w:spacing w:before="480" w:after="0" w:line="240" w:lineRule="auto"/></w:pPr><w:rPr><w:i/><w:color w:val="7F7F7F"/><w:sz w:val="18"/><w:szCs w:val="18"/></w:rPr></w:style>
<w:style w:type="table" w:default="1" w:styleId="TableNormal"><w:name w:val="Normal Table"/><w:tblPr><w:tblInd w:w="0" w:type="dxa"/><w:tblCellMar><w:top w:w="0" w:type="dxa"/><w:left w:w="80" w:type="dxa"/><w:bottom w:w="0" w:type="dxa"/><w:right w:w="80" w:type="dxa"/></w:tblCellMar></w:tblPr></w:style>
</w:styles>"""

# Declares the current Word format (compatibility mode 15), so Word does not open the file in Compatibility Mode.
SETTINGS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:settings xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:compat><w:compatSetting w:name="compatibilityMode" w:uri="http://schemas.microsoft.com/office/word" w:val="15"/></w:compat></w:settings>"""


# A subscript is written as x_y in the source text: a 1-2 letter symbol, "_", then the subscript (letters, digits,
# ∞, and one optional ",word" part as in c_p,eff). Longer prefixes (confirm_c1, part_5) are identifiers, left as is.
SUBSCRIPT = re.compile(r"(?<![A-Za-zΑ-Ωα-ω])([A-Za-zΑ-Ωα-ωΔ]{1,2})_([A-Za-z0-9∞]+(?:,[A-Za-z]+)?)")


def _run(text: str, *, bold: bool | None = None, italic: bool = False, sz: int | None = None) -> str:
    """Runs for text, with x_y written as x and a subscript y."""

    out, pos = [], 0
    for m in SUBSCRIPT.finditer(text):
        out.append(_plain(text[pos:m.start(2) - 1], bold=bold, italic=italic, sz=sz))
        out.append(_plain(m.group(2), bold=bold, italic=italic, sz=sz, sub=True))
        pos = m.end()
    out.append(_plain(text[pos:], bold=bold, italic=italic, sz=sz))
    return "".join(o for o in out if o)


def _plain(text: str, *, bold: bool | None = None, italic: bool = False, sz: int | None = None,
           sub: bool = False) -> str:
    if not text:
        return ""
    props = []
    if bold is True:
        props.append("<w:b/>")
    elif bold is False:
        props.append('<w:b w:val="0"/><w:bCs w:val="0"/>')
    if italic:
        props.append("<w:i/>")
    if sz:
        props.append(f'<w:sz w:val="{sz}"/><w:szCs w:val="{sz}"/>')
    if sub:
        props.append('<w:vertAlign w:val="subscript"/>')
    rpr = f"<w:rPr>{''.join(props)}</w:rPr>" if props else ""
    parts = text.split("\n")
    body = '<w:br/>'.join(f'<w:t xml:space="preserve">{escape(p)}</w:t>' for p in parts)
    return f"<w:r>{rpr}{body}</w:r>"


def _para(style: str, runs: str, *, jc: str | None = None, extra_ppr: str = "") -> str:
    ppr = f'<w:pStyle w:val="{style}"/>' + (f'<w:jc w:val="{jc}"/>' if jc else "") + extra_ppr
    return f"<w:p><w:pPr>{ppr}</w:pPr>{runs}</w:p>"


def _seq(kind: str, number: int) -> str:
    return (f'<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            f'<w:r><w:instrText xml:space="preserve"> SEQ {kind} \\* ARABIC </w:instrText></w:r>'
            f'<w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:t>{number}</w:t></w:r>'
            f'<w:r><w:fldChar w:fldCharType="end"/></w:r>')


NUMERIC = re.compile(r"^[\s−+\-\d\[(×–≈≤<>.]")


def _table(columns: list[str], rows: list[list[str]], widths: list[float] | None, *, group_rows: bool = False,
           rule_before: int | None = None) -> str:
    n = len(columns)
    widths = widths or [1.0 / n] * n
    total = sum(widths)
    tw = [int(TEXT_WIDTH_TWIPS * w / total) for w in widths]
    center = []
    for j in range(n):
        vals = [r[j] for r in rows if j < len(r) and r[j]]
        center.append(j > 0 and bool(vals) and max(len(v) for v in vals) <= 22
                      and sum(1 for v in vals if NUMERIC.match(v)) / len(vals) > 0.6)
    border = '<w:{0} w:val="single" w:sz="{1}" w:space="0" w:color="000000"/>'
    tblpr = (f'<w:tblPr><w:tblW w:w="{TEXT_WIDTH_TWIPS}" w:type="dxa"/><w:tblLayout w:type="fixed"/>'
             f'<w:tblBorders>{border.format("top", 8)}{border.format("bottom", 8)}</w:tblBorders>'
             f'<w:tblCellMar><w:left w:w="70" w:type="dxa"/><w:right w:w="70" w:type="dxa"/></w:tblCellMar>'
             f'<w:tblLook w:val="0000" w:firstRow="0" w:lastRow="0" w:firstColumn="0" w:lastColumn="0" '
             f'w:noHBand="1" w:noVBand="1"/></w:tblPr>')
    grid = "<w:tblGrid>" + "".join(f'<w:gridCol w:w="{w}"/>' for w in tw) + "</w:tblGrid>"

    def cell(text, j, *, header=False, span=1, bold=False, top_rule=False):
        w = sum(tw[j:j + span])
        tcpr = f'<w:tcW w:w="{w}" w:type="dxa"/>'
        if span > 1:
            tcpr += f'<w:gridSpan w:val="{span}"/>'
        borders = []
        if header:
            borders.append(border.format("bottom", 6))
        if top_rule:
            borders.append(border.format("top", 4))
        if borders:
            tcpr += f"<w:tcBorders>{''.join(borders)}</w:tcBorders>"
        tcpr += '<w:vAlign w:val="bottom"/>' if header else ""
        jc = "center" if (center[j] and span == 1) else None
        p = _para("TableText", _run(text, bold=True if (header or bold) else None), jc=jc)
        return f"<w:tc><w:tcPr>{tcpr}</w:tcPr>{p}</w:tc>"

    out = [f"<w:tbl>{tblpr}{grid}"]
    out.append('<w:tr><w:trPr><w:tblHeader/><w:cantSplit/></w:trPr>'
               + "".join(cell(c, j, header=True) for j, c in enumerate(columns)) + "</w:tr>")
    for i, r in enumerate(rows):
        is_group = group_rows and all(not x for x in r[1:])
        top = rule_before is not None and i == rule_before
        if is_group:
            out.append('<w:tr><w:trPr><w:cantSplit/></w:trPr>'
                       + cell(r[0], 0, span=n, bold=True, top_rule=(i > 0)) + "</w:tr>")
        else:
            out.append('<w:tr><w:trPr><w:cantSplit/></w:trPr>'
                       + "".join(cell(x, j, top_rule=top) for j, x in enumerate(r)) + "</w:tr>")
    out.append("</w:tbl>")
    return "".join(out)


def _png_size(path: Path) -> tuple[int, int]:
    head = path.read_bytes()[:24]
    w, h = struct.unpack(">II", head[16:24])
    return w, h


def _drawing(rid: str, pid: int, name: str, path: Path, dpi: float = 300.0) -> str:
    wpx, hpx = _png_size(path)
    w_in, h_in = wpx / dpi, hpx / dpi
    if w_in > TEXT_WIDTH_IN:
        h_in *= TEXT_WIDTH_IN / w_in
        w_in = TEXT_WIDTH_IN
    cx, cy = int(w_in * EMU_PER_IN), int(h_in * EMU_PER_IN)
    return (f'<w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0"><wp:extent cx="{cx}" cy="{cy}"/>'
            f'<wp:docPr id="{pid}" name="{escape(name)}"/><wp:cNvGraphicFramePr>'
            f'<a:graphicFrameLocks noChangeAspect="1"/></wp:cNvGraphicFramePr><a:graphic><a:graphicData '
            f'uri="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:pic><pic:nvPicPr>'
            f'<pic:cNvPr id="{pid}" name="{escape(path.name)}"/><pic:cNvPicPr/></pic:nvPicPr><pic:blipFill>'
            f'<a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill><pic:spPr><a:xfrm>'
            f'<a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/>'
            f'</a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r>')


def write_docx(path: Path, title: str, intro: list[str], items: list[dict]) -> None:
    """items: dicts with kind 'table' or 'figure', placement, title, note, and table/figure fields."""

    body = [_para("Heading1", _run(title))]
    for line in intro:
        body.append(_para("TableNote", _run(line)))
    media = []
    n_tab = n_fig = 0
    for item in items:
        body.append(_para("Placement", _plain(f"{item['id']} · {item['placement']}")))
        if item["kind"] == "table":
            n_tab += 1
            body.append(_para("TableTitle", _run("Table ") + _seq("Table", n_tab) + _run(f". {item['title']}")))
            body.append(_table(item["columns"], item["rows"], item.get("widths"), group_rows=item.get("group_rows", False),
                               rule_before=item.get("group_from")))
            if item.get("note"):
                body.append(_para("TableNote", _run("Note. ", italic=True) + _run(item["note"])))
            else:
                body.append(_para("TableNote", ""))
        else:
            n_fig += 1
            rid = f"rIdImg{n_fig}"
            media.append((rid, f"media/figure{n_fig:02d}.png", item["png"]))
            body.append(_para("Figure", _drawing(rid, n_fig, f"Figure {n_fig}", item["png"])))
            body.append(_para("Caption", _run("Figure ") + _seq("Figure", n_fig) + _run(f". {item['title']}.")
                              + (_run(" " + item["note"], bold=False) if item.get("note") else "")))
    sect = (f'<w:sectPr><w:pgSz w:w="12240" w:h="15840"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" '
            f'w:left="1800" w:header="720" w:footer="720" w:gutter="0"/></w:sectPr>')
    document = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<w:document {NS}><w:body>'
                + "".join(body) + sect + "</w:body></w:document>")
    rels = ['<Relationship Id="rIdStyles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
            'styles" Target="styles.xml"/>',
            '<Relationship Id="rIdSettings" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
            'settings" Target="settings.xml"/>']
    for rid, target, _ in media:
        rels.append(f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                    f'relationships/image" Target="{target}"/>')
    doc_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="http://schemas.'
                'openxmlformats.org/package/2006/relationships">' + "".join(rels) + "</Relationships>")
    content_types = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Types xmlns="http://schemas.'
                     'openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="'
                     'application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" '
                     'ContentType="application/xml"/><Default Extension="png" ContentType="image/png"/><Override '
                     'PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.'
                     'wordprocessingml.document.main+xml"/><Override PartName="/word/styles.xml" ContentType="'
                     'application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/><Override '
                     'PartName="/word/settings.xml" ContentType="application/vnd.openxmlformats-officedocument.'
                     'wordprocessingml.settings+xml"/></Types>')
    root_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="http://schemas.'
                 'openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.'
                 'openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
                 '</Relationships>')
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        def put(name, data):
            info = zipfile.ZipInfo(name, date_time=ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data)

        put("[Content_Types].xml", content_types)
        put("_rels/.rels", root_rels)
        put("word/document.xml", document)
        put("word/styles.xml", STYLES)
        put("word/settings.xml", SETTINGS)
        put("word/_rels/document.xml.rels", doc_rels)
        for _, target, png in media:
            put(f"word/{target}", Path(png).read_bytes())
