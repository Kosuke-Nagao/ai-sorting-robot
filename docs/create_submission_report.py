from pathlib import Path
from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.shared import Inches, Pt, RGBColor
from docx.oxml import OxmlElement
from docx.oxml.ns import qn


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "説明資料_PAI最終課題_46467_更新版.docx"
SUCCESS_IMAGE = Path(r"C:\Users\honor\AppData\Local\Temp\codex-clipboard-fe55792c-e02d-4c71-8b19-da427754e2f1.png")
FAILURE_IMAGE = Path(r"C:\Users\honor\AppData\Local\Temp\codex-clipboard-e4b45e58-9de3-40b6-807b-21f0f2a1b5b9.png")

NAVY = "163A5F"
BLUE = "2B74B8"
PALE_BLUE = "EAF3FA"
PALE_GRAY = "F5F7F9"
GRID = "D9E1E8"
BLACK = "000000"


def set_run_font(run, name="Yu Gothic", size=None, bold=None, color=None, italic=None):
    run.font.name = name
    run._element.get_or_add_rPr().rFonts.set(qn("w:ascii"), name)
    run._element.get_or_add_rPr().rFonts.set(qn("w:hAnsi"), name)
    run._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), name)
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.bold = bold
    if italic is not None:
        run.italic = italic
    if color:
        run.font.color.rgb = RGBColor.from_string(color)


def set_cell_shading(cell, fill):
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = tc_pr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        tc_pr.append(shd)
    shd.set(qn("w:fill"), fill)


def set_cell_margins(cell, top=100, start=130, bottom=100, end=130):
    tc = cell._tc
    tc_pr = tc.get_or_add_tcPr()
    tc_mar = tc_pr.first_child_found_in("w:tcMar")
    if tc_mar is None:
        tc_mar = OxmlElement("w:tcMar")
        tc_pr.append(tc_mar)
    for m, v in (("top", top), ("start", start), ("bottom", bottom), ("end", end)):
        node = tc_mar.find(qn(f"w:{m}"))
        if node is None:
            node = OxmlElement(f"w:{m}")
            tc_mar.append(node)
        node.set(qn("w:w"), str(v))
        node.set(qn("w:type"), "dxa")


def set_cell_borders(cell, color=GRID, size="6"):
    tc_pr = cell._tc.get_or_add_tcPr()
    borders = tc_pr.first_child_found_in("w:tcBorders")
    if borders is None:
        borders = OxmlElement("w:tcBorders")
        tc_pr.append(borders)
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        tag = f"w:{edge}"
        element = borders.find(qn(tag))
        if element is None:
            element = OxmlElement(tag)
            borders.append(element)
        element.set(qn("w:val"), "single")
        element.set(qn("w:sz"), size)
        element.set(qn("w:space"), "0")
        element.set(qn("w:color"), color)


def set_col_width(cell, width_inches):
    cell.width = Inches(width_inches)
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_w = tc_pr.find(qn("w:tcW"))
    if tc_w is None:
        tc_w = OxmlElement("w:tcW")
        tc_pr.append(tc_w)
    tc_w.set(qn("w:w"), str(int(width_inches * 1440)))
    tc_w.set(qn("w:type"), "dxa")


def keep_with_next(paragraph):
    paragraph.paragraph_format.keep_with_next = True


def add_page_field(paragraph):
    run = paragraph.add_run()
    fld_char1 = OxmlElement("w:fldChar")
    fld_char1.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = " PAGE "
    fld_char2 = OxmlElement("w:fldChar")
    fld_char2.set(qn("w:fldCharType"), "end")
    run._r.append(fld_char1)
    run._r.append(instr)
    run._r.append(fld_char2)
    set_run_font(run, size=9, color="6B7280")


def add_heading(doc, text, level=1):
    p = doc.add_paragraph(style=f"Heading {level}")
    p.paragraph_format.space_before = Pt(14 if level == 1 else 9)
    p.paragraph_format.space_after = Pt(5)
    r = p.add_run(text)
    set_run_font(r, size=16 if level == 1 else 12.5, bold=True, color=BLACK)
    keep_with_next(p)
    return p


def add_body(doc, text, space_after=6, first_line=True):
    p = doc.add_paragraph(style="Normal")
    p.paragraph_format.space_after = Pt(space_after)
    p.paragraph_format.line_spacing = 1.15
    if first_line:
        p.paragraph_format.first_line_indent = Inches(0.22)
    r = p.add_run(text)
    set_run_font(r, size=10.8, color=BLACK)
    return p


def add_bullet(doc, text, level=0):
    p = doc.add_paragraph(style="List Bullet" if level == 0 else "List Bullet 2")
    p.paragraph_format.space_after = Pt(3)
    p.paragraph_format.line_spacing = 1.08
    r = p.add_run(text)
    set_run_font(r, size=10.4, color=BLACK)
    return p


def add_caption(doc, text):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(3)
    p.paragraph_format.space_after = Pt(8)
    r = p.add_run(text)
    set_run_font(r, size=9, color="5B6570", italic=True)
    return p


def add_picture_with_alt(doc, path, width, caption):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(4)
    p.paragraph_format.space_after = Pt(0)
    run = p.add_run()
    run.add_picture(str(path), width=Inches(width))
    inline = run._r.xpath(".//wp:inline")
    if inline:
        doc_pr = inline[0].find(qn("wp:docPr"))
        if doc_pr is not None:
            doc_pr.set("descr", caption)
            doc_pr.set("title", caption)
    add_caption(doc, caption)


def add_table(doc, headers, rows, widths, font_size=9.3, header_fill=NAVY):
    table = doc.add_table(rows=1, cols=len(headers))
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    for i, h in enumerate(headers):
        cell = table.rows[0].cells[i]
        set_col_width(cell, widths[i])
        set_cell_shading(cell, header_fill)
        set_cell_margins(cell)
        set_cell_borders(cell)
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_after = Pt(0)
        r = p.add_run(h)
        set_run_font(r, size=font_size, bold=True, color="FFFFFF")
    for ridx, row in enumerate(rows):
        cells = table.add_row().cells
        for i, value in enumerate(row):
            cell = cells[i]
            set_col_width(cell, widths[i])
            set_cell_margins(cell)
            set_cell_borders(cell)
            if ridx % 2 == 1:
                set_cell_shading(cell, PALE_GRAY)
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            p = cell.paragraphs[0]
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.line_spacing = 1.05
            r = p.add_run(str(value))
            set_run_font(r, size=font_size, color=BLACK)
    doc.add_paragraph().paragraph_format.space_after = Pt(1)
    return table


def add_process_table(doc):
    rows = [
        ("1 指示", "自然言語入力", "赤いキューブを左へ / 黄色いキューブを右へ"),
        ("2 解釈", "Ollama qwen2.5:3b", "色と仕分け先だけを制約付きJSONへ変換"),
        ("3 検証", "SortCommand", "許可された色・方向以外は拒否"),
        ("4 制御", "ROS 2 / MoveIt 2", "PTPで接近し、LINで持ち上げ・搬送・配置"),
        ("5 確認", "Gazebo / noVNC", "リンク接続、水平姿勢、マット内配置を確認"),
    ]
    return add_table(doc, ["段階", "担当", "処理"], rows, [0.9, 1.65, 3.55], font_size=9.0, header_fill=BLUE)


def setup_styles(doc):
    styles = doc.styles
    normal = styles["Normal"]
    normal.font.name = "Yu Gothic"
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), "Yu Gothic")
    normal.font.size = Pt(10.8)
    for name, size in (("Title", 25), ("Heading 1", 16), ("Heading 2", 12.5)):
        st = styles[name]
        st.font.name = "Yu Gothic"
        st._element.rPr.rFonts.set(qn("w:eastAsia"), "Yu Gothic")
        st.font.size = Pt(size)
        st.font.color.rgb = RGBColor.from_string(BLACK)
        st.font.bold = True
        # Word's built-in Title style can carry a theme-colored bottom rule.
        # Remove it so the report uses whitespace and typography for hierarchy.
        p_pr = st._element.get_or_add_pPr()
        p_bdr = p_pr.find(qn("w:pBdr"))
        if p_bdr is not None:
            p_pr.remove(p_bdr)


def main():
    doc = Document()
    setup_styles(doc)
    section = doc.sections[0]
    section.page_width = Inches(8.5)
    section.page_height = Inches(11)
    section.top_margin = Inches(0.72)
    section.bottom_margin = Inches(0.68)
    section.left_margin = Inches(0.78)
    section.right_margin = Inches(0.78)
    section.header_distance = Inches(0.35)
    section.footer_distance = Inches(0.35)

    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    fr = footer.add_run("AI仕分けロボット  |  ")
    set_run_font(fr, size=8.5, color="6B7280")
    add_page_field(footer)

    # Cover page
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(38)
    p.paragraph_format.space_after = Pt(16)
    r = p.add_run("PAI 最終課題 説明資料")
    set_run_font(r, size=12, bold=True, color=BLUE)
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER

    p = doc.add_paragraph(style="Title")
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(20)
    p.paragraph_format.space_after = Pt(15)
    r = p.add_run("AI×ロボティクスによる創造的タスクの実現")
    set_run_font(r, size=25, bold=True, color=BLACK)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(50)
    r = p.add_run("自然言語で指示できる AI 仕分けロボット")
    set_run_font(r, size=15, bold=True, color=NAVY)
    p.add_run("\n")
    r = p.add_run("ROS 2・MoveIt 2・Gazebo・Ollama によるシミュレーション")
    set_run_font(r, size=10.5, color="5B6570")

    meta = [
        ("提出者", "honor"),
        ("実行環境", "Windows + Docker Compose + noVNC"),
        ("対象タスク", "色を指定したキューブの左右仕分け"),
        ("提出日", "2026年11月2日"),
    ]
    add_table(doc, ["項目", "内容"], meta, [1.25, 4.85], font_size=9.7, header_fill=NAVY)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(45)
    p.paragraph_format.space_after = Pt(0)
    r = p.add_run("本資料は、課題の目的、実装、評価基準への対応、検証中の改善点をまとめたものです。")
    set_run_font(r, size=9.5, color="5B6570")
    doc.add_page_break()

    # Page 2: overview and architecture
    add_heading(doc, "1 課題の概要と目的", 1)
    add_body(doc, "本課題では、利用者が「赤いキューブを左へ」「黄色いキューブを右へ」のように自然言語で指示すると、ローカルLLMが対象物と仕分け先を解釈し、UR3ロボットがGazebo上でピックアンドプレースを実行するシステムを制作した。")
    add_body(doc, "狙いは、自然言語の柔軟性と、ROS 2・MoveIt 2による再現可能なロボット制御を安全に接続することである。LLMには座標や関節角度を生成させず、高水準の「色」と「左右」だけを決めさせることで、AIの判断範囲を明確に限定した。")

    add_heading(doc, "2 システム構成", 1)
    add_table(doc, ["要素", "採用技術", "役割"], [
        ("入力", "日本語・英語の自然言語", "利用者が仕分け内容を指定"),
        ("AI", "Ollama / qwen2.5:3b", "色と仕分け先をJSONへ変換"),
        ("制御", "ROS 2 Humble / rclpy", "検証済み命令をActionへ接続"),
        ("経路計画", "MoveIt 2 / Robmove", "PTP・LINの移動を実行"),
        ("シミュレータ", "Gazebo Classic 11", "UR3、グリッパー、作業台を再現"),
        ("表示", "Docker Compose / noVNC", "Windowsのブラウザから動作確認"),
    ], [1.05, 2.0, 3.05], font_size=8.9)

    add_heading(doc, "3 指示から配置までの処理", 1)
    add_process_table(doc)
    add_body(doc, "LLMの結果は、例えば {\"color\": \"red\", \"destination\": \"left\"} のような形式に限定する。許可されていない色や方向、曖昧な指示はロボットへ渡さず、dry-runで判断だけを確認できる。", first_line=False)
    doc.add_page_break()

    # Page 3: AI and implementation
    add_heading(doc, "4 AIの活用方法", 1)
    add_body(doc, "AIは「何をどこへ移動するか」という高水準の意味理解に使用した。実際の座標、速度、把持姿勢、関節軌道は、検証済みのPythonノードとMoveIt 2が担当する。この分離により、自然言語インターフェースを維持しながら、ロボットの動作範囲を色と左右の仕分けに制約できる。")
    add_bullet(doc, "利用モデル: Ollama上の qwen2.5:3b（ローカル推論、追加学習なし）")
    add_bullet(doc, "出力検証: SortCommandで色と仕分け先の許可リストを確認")
    add_bullet(doc, "安全側の設計: JSON不正、未対応語、曖昧な指示は実行せずエラーとして返す")

    add_heading(doc, "5 実装上の工夫", 1)
    add_table(doc, ["工夫", "実装内容", "ねらい"], [
        ("最終位置の再取得", "接近直前にGazebo上のキューブ位置を再取得し、アプローチ座標を更新", "物理演算による微小な移動への追従"),
        ("把持位置の校正", "リンク原点と見た目の中心の差を測定し、把持後オフセットを適用", "指先とキューブ中心のずれを抑制"),
        ("固定リンク把持", "把持後にアタッチ機能を使い、搬送中の回転・滑りを抑制", "エミュレーション環境での再現性を確保"),
        ("姿勢の正規化", "配置前にキューブのyawを0へ戻し、マットに水平に置く", "見た目と配置結果を安定化"),
        ("移動方式の使い分け", "PTPで安全な中間位置へ移動し、LINでリフトと配置を実行", "動作の滑らかさと経路の再現性を両立"),
    ], [1.15, 3.15, 1.8], font_size=8.75)

    add_heading(doc, "6 実行結果", 1)
    add_body(doc, "「赤いキューブを左へ」「黄色いキューブを右へ」の両方を確認し、LLMの判断からピック、搬送、マット上への配置、退避までを完了した。黄色キューブの実行ログには、把持、デタッチ、配置後の退避が順番に記録され、最後に成功メッセージが出力された。")
    add_picture_with_alt(doc, SUCCESS_IMAGE, 5.75, "図1 最終確認時の成功例（黄色キューブを右側マットへ配置）")
    doc.add_page_break()

    # Page 4: grading criteria
    add_heading(doc, "7 評価基準への対応", 1)
    add_body(doc, "本課題の評価基準に対して、実装した内容と提出時に示す証拠を次のように整理した。合格ラインである「ロボットがタスクを実行する動画と提出物」に加え、独自性、実装の深さ、応用可能性、説明の分かりやすさを意識して構成している。")
    add_table(doc, ["評価軸", "実装・工夫", "提出時に示すもの"], [
        ("合格ライン", "自然言語の指示に応じてキューブを左右のマットへ移動", "1〜3分の動作動画、コード一式、説明資料"),
        ("創造性", "固定コマンドではなく、日常的な日本語をLLMで仕分け命令へ変換", "入力文、LLM decision、Gazebo動作の一連の記録"),
        ("技術力", "LLM、ROS 2 Action、MoveIt 2、Gazebo物理、リンクアタッチを統合", "README、ソースコード、実行ログ、Docker構成"),
        ("実用性", "倉庫・リサイクル・製造ラインの色分け搬送へ発展可能。ローカル推論で外部APIに依存しない", "用途説明、制約、今後のカメラ認識計画"),
        ("表現力", "指示、AI判断、ロボット動作、配置結果を同じ動画内で示す", "画面構成案、字幕、成功時ログ"),
    ], [1.05, 3.35, 1.7], font_size=8.65)

    add_heading(doc, "8 独自実装と利用コンポーネントの区分", 1)
    add_body(doc, "ROS 2、Gazebo、MoveIt 2、UR3/Robotiqモデル、リンクアタッチ機能などは既存のオープンソース部品を利用し、外部依存はdependencies.reposでコミットを固定した。一方、自然言語パーサ、許可リスト検証、キューブ位置の再取得、把持オフセットの校正、配置姿勢の正規化、Docker/noVNC向けの実行環境調整、説明資料は本課題のために構成・実装した部分である。")
    add_body(doc, "既存部品の名称やライセンスを隠さず、利用箇所と自作箇所を分けて説明することで、他人の作品の剽窃や最終課題サンプルの丸写しと誤解されない提出形態にしている。", first_line=False)
    doc.add_page_break()

    # Page 5-6: improvements
    add_heading(doc, "9 うまくいかなかった点と改善", 1)
    add_body(doc, "検証では、動作成功だけでなく、画面上で把持に見えない、キューブが傾く、配置後に再び持ち上げたように見える、といった問題も確認した。以下では、観察した現象、原因の仮説、実施した改善、残る制約を区別して記載する。")
    add_body(doc, "今回の検証を通じて、Robotの動きだけでなく、Cube側の動きも適切に設定する必要があると分かった。Robotの軌道だけを調整しても、Cubeの重力、接触、固定リンク、配置後の状態遷移が整っていなければ、Cubeが指先からずれたり、マットへ沈み込んだり、消滅したように見えたりする不自然なシミュレーションになる。そこで、把持前の物理接触による押し出しを抑え、把持後は固定リンクで搬送し、配置後は静的Cubeへ切り替えることで、見た目の一貫性を改善した。")
    add_table(doc, ["問題", "原因・観察", "実施した改善", "残る課題"], [
        ("指先がキューブの端に見える", "グリッパーのリンク原点と可視メッシュの中心が一致せず、視点によって奥側の指先が露出", "把持姿勢を固定し、把持後オフセットを校正。中心間の保持ログを追加", "接触位置を画像で閉ループ確認していない"),
        ("キューブが傾く・水平に見えない", "把持時の姿勢とアタッチ後の相対姿勢が一致しない場合がある", "一定のエンドエフェクタ姿勢、yaw正規化、配置前の水平化処理を追加", "実機へ移す場合は力覚と接触モデルが必要"),
        ("置いた後に再び持ち上げたように見える", "デタッチ後の退避動作と物理落下が連続し、画面上で順序が分かりにくい", "デタッチ、開放、配置確認、退避をログと処理順に分離", "動画では字幕で状態遷移を補足する"),
        ("計画失敗・Action timeout", "ARM64上のx86エミュレーションとGazebo負荷で計画・実行が不安定", "中間姿勢を固定し、PTP/LINを使い分け、サーバ待機とリトライを実装", "実時間係数が1未満になる場合がある"),
        ("グリッパーの見た目と物理接触の差", "摩擦接触だけではキューブが滑るため、成功状態と見た目に差が出る", "リンクアタッチを固定ジョイントとしてビルドし、搬送中のずれを抑制", "純粋な接触把持ではなく、物理的妥当性は今後の課題"),
        ("既知座標に依存", "対象物認識はGazeboモデル名と既知配置を利用", "実位置を接近前に再取得して座標を更新", "RGB-Dカメラによる認識は未実装"),
    ], [1.05, 1.65, 2.15, 1.25], font_size=8.0)
    add_picture_with_alt(doc, FAILURE_IMAGE, 5.45, "図2 検証中に確認した失敗例（キューブが台から外れた状態）")

    add_heading(doc, "10 今後の改善方針", 1)
    add_body(doc, "Robotの動作には、PTPとLIN、固定した中間姿勢を使うことで再現性を持たせているが、関節移動がカクカクして見える場面は残っている。今後は速度・加速度・補間方法・経路分割を調整し、把持、リフト、搬送、配置、退避までをより滑らかに見せることを改善点とする。")
    add_bullet(doc, "カメラ画像からキューブの中心・姿勢・マット境界を検出し、把持直前と配置直後に画像確認する")
    add_bullet(doc, "指先の接触位置を左右の画像特徴で評価し、中心から外れた場合は再アプローチする")
    add_bullet(doc, "アタッチに頼らない接触・摩擦モデルを調整し、物理シミュレーション上の把持妥当性を高める")
    add_bullet(doc, "複数キューブの一括指示、障害物回避、配置成否の自動判定を追加する")
    doc.add_page_break()

    # Page 7: video plan and conclusion
    add_heading(doc, "11 動画の構成案", 1)
    add_body(doc, "提出動画は1〜3分に収め、自然言語入力、LLMの判断、ピック、リフト、搬送、配置結果が連続して理解できる構成にする。動作が長い場合は2倍速を使用し、画面内に「2倍速」と明記する。")
    add_table(doc, ["時間", "内容", "画面上の説明"], [
        ("0:00〜0:10", "課題名と目的", "自然言語で仕分けるAIロボット"),
        ("0:10〜0:25", "Gazebo作業環境", "UR3、グリッパー、3色キューブ、左右マット"),
        ("0:25〜0:40", "自然言語入力とLLM判断", "color=yellow, destination=right"),
        ("0:40〜1:30", "ピック・リフト・搬送・配置", "把持、水平姿勢、デタッチ、退避"),
        ("1:30〜1:50", "配置結果とログ", "SUCCESSメッセージ、マット内配置"),
        ("1:50〜2:10", "工夫と改善点", "位置校正、固定リンク、制約付きLLM"),
    ], [1.05, 2.35, 2.7], font_size=8.8)

    add_heading(doc, "12 まとめ", 1)
    add_body(doc, "本課題では、ローカルLLMを自然言語インターフェースとして利用し、ROS 2・MoveIt 2・Gazebo上のUR3ロボットへ安全に接続した。色と左右という単純なタスクに絞ることで、AIの柔軟な解釈と、低水準制御の再現性を両立した。")
    add_body(doc, "検証では、把持位置の見え方、キューブの水平姿勢、配置後の状態遷移、シミュレーション負荷などの問題が現れたが、位置再取得、把持オフセット校正、固定リンク、姿勢正規化、ログの明確化によって改善した。今後はカメラ認識と接触ベースの閉ループ制御を追加し、見た目にも物理的にも自然な把持へ発展させる。")

    # Core properties
    doc.core_properties.title = "AI×ロボティクスによる創造的タスクの実現"
    doc.core_properties.subject = "PAI最終課題 説明資料"
    doc.core_properties.author = "honor"
    doc.core_properties.keywords = "ROS 2, Gazebo, MoveIt 2, Ollama, AI, 仕分けロボット"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(OUT)
    print(OUT)


if __name__ == "__main__":
    main()
