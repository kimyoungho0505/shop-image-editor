"""Shadow Hints Management Tab (PySide6)."""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSplitter, QGroupBox, QTextEdit, QTreeWidget, QTreeWidgetItem,
    QMessageBox, QDialog, QComboBox, QLineEdit,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QColor

from gui_pyside.utils import load_yaml, save_yaml, SHADOW_HINTS_PATH
from gui_pyside.styles import ACCENT, FONT_FAMILY, SUCCESS, DANGER, CARD_BG


class HintsTab(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self._shadow_hints_data = {}
        self._current_hint_key = None
        self._build_ui()
        self.load_shadow_hints()

    def _build_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(12, 8, 12, 8)

        # -- Header --
        header_row = QHBoxLayout()
        title_lbl = QLabel("그림자 힌트 관리")
        title_lbl.setStyleSheet(f"font-size: 13pt; font-weight: bold; font-family: '{FONT_FAMILY}';")
        header_row.addWidget(title_lbl)
        desc_lbl = QLabel("카테고리 / 촬영방향 / 촬영유형 조합별 그림자 프롬프트 보충 지시")
        desc_lbl.setStyleSheet(f"font-size: 9pt; color: #6b7280; font-family: '{FONT_FAMILY}';")
        header_row.addWidget(desc_lbl)
        header_row.addStretch()
        root_layout.addLayout(header_row)

        # -- Priority info --
        prio1 = QLabel(
            "조회 우선순위:  provider/category/angle/type  >  category/angle  >  category  >  angle  >  default")
        prio1.setStyleSheet(f"font-size: 8pt; color: #9ca3af; font-family: '{FONT_FAMILY}';")
        root_layout.addWidget(prio1)
        prio2 = QLabel(
            "main_prompt(공통 규칙) + 매칭된 hint(조건별 보충) = 최종 프롬프트  |  "
            "자동수정 시 해당 키의 hint만 변경되므로 다른 상품에 영향 없음")
        prio2.setStyleSheet(f"font-size: 8pt; color: #9ca3af; font-family: '{FONT_FAMILY}';")
        root_layout.addWidget(prio2)

        # -- Button bar --
        btn_row = QHBoxLayout()

        btn_save = QPushButton("  선택 항목 저장  ")
        btn_save.setProperty("cssClass", "accent")
        btn_save.clicked.connect(self.on_hint_edit_save)
        btn_row.addWidget(btn_save)

        btn_add = QPushButton("새 힌트 추가")
        btn_add.clicked.connect(self.on_hint_add)
        btn_row.addWidget(btn_add)

        btn_del = QPushButton("삭제")
        btn_del.clicked.connect(self.on_hint_delete)
        btn_row.addWidget(btn_del)

        btn_reload = QPushButton("파일에서 다시 불러오기")
        btn_reload.clicked.connect(self.load_shadow_hints)
        btn_row.addWidget(btn_reload)

        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet(f"font-family: '{FONT_FAMILY}';")
        btn_row.addWidget(self.lbl_status)
        btn_row.addStretch()
        root_layout.addLayout(btn_row)

        # -- Main area (splitter) --
        splitter = QSplitter(Qt.Horizontal)

        # Left: tree
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)

        self.hint_tree = QTreeWidget()
        self.hint_tree.setHeaderLabels(["키", "미리보기"])
        self.hint_tree.setColumnWidth(0, 180)
        self.hint_tree.setAlternatingRowColors(True)
        self.hint_tree.currentItemChanged.connect(self._on_tree_item_changed)
        left_layout.addWidget(self.hint_tree)

        splitter.addWidget(left_widget)

        # Right: editor
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self.lbl_hint_key = QLabel("(항목을 선택하세요)")
        self.lbl_hint_key.setStyleSheet(
            f"font-size: 10pt; font-weight: bold; color: {ACCENT}; font-family: '{FONT_FAMILY}';")
        right_layout.addWidget(self.lbl_hint_key)

        self.txt_hint_editor = QTextEdit()
        self.txt_hint_editor.setStyleSheet("background: #f5f0ff;")
        right_layout.addWidget(self.txt_hint_editor, 1)

        # Guide
        grp_guide = QGroupBox("작성 가이드")
        grp_guide_layout = QVBoxLayout(grp_guide)
        guide_text = (
            "- 이 힌트는 메인 프롬프트(공통) 뒤에 추가되어 최종 프롬프트를 구성합니다\n"
            "- 해당 카테고리/촬영방향에 특화된 그림자 지시를 작성하세요\n"
            "- 예: 모자 -> '챙(brim) 곡선을 따라 접지 그림자 생성, 챙 끝이 바닥에 닿지 않는 부분은 제외'\n"
            "- 예: 신발/측면 -> '밑창 전체가 바닥에 닿으므로 밑창 윤곽을 따라 그림자 생성'\n"
            "- 자동수정 시 AI가 이 힌트를 분석하여 개선안을 제안합니다"
        )
        guide_lbl = QLabel(guide_text)
        guide_lbl.setStyleSheet(f"font-size: 8pt; color: #6b7280; font-family: '{FONT_FAMILY}';")
        guide_lbl.setWordWrap(True)
        grp_guide_layout.addWidget(guide_lbl)
        right_layout.addWidget(grp_guide)

        splitter.addWidget(right_widget)
        splitter.setSizes([300, 500])

        root_layout.addWidget(splitter, 1)

    # ── Tree helpers ──

    def _on_tree_item_changed(self, current, _previous):
        if current is None:
            return
        key = current.data(0, Qt.UserRole)
        if key is None:
            self.txt_hint_editor.clear()
            self._current_hint_key = None
            self.lbl_hint_key.setText("(그룹 선택 -- 하위 항목을 선택하세요)")
            return
        self._current_hint_key = key
        self.lbl_hint_key.setText(f"편집 중: {key}")
        self.txt_hint_editor.setPlainText(self._shadow_hints_data.get(key, ""))

    on_hint_select = _on_tree_item_changed

    # ── Data methods ──

    def load_shadow_hints(self):
        try:
            data = load_yaml(SHADOW_HINTS_PATH)
            if not isinstance(data, dict):
                data = {}
            self._shadow_hints_data = {k: str(v).strip() for k, v in data.items()}
            self.rebuild_hint_tree()
            self.txt_hint_editor.clear()
            self._current_hint_key = None
            self._show_status("힌트 로드 완료", SUCCESS)
        except Exception as e:
            self._show_status(f"힌트 로드 실패: {e}", DANGER)

    def rebuild_hint_tree(self):
        tree = self.hint_tree
        tree.clear()

        KNOWN_ANGLES = {"front", "high_angle", "top_down", "side", "detail", "held", "worn"}
        KNOWN_TYPES = {"full", "detail", "worn", "package"}
        KNOWN_PROVIDERS = {"gemini", "gemini_shadow", "grok", "grok_shadow"}

        group_default = {}
        group_angle = {}
        group_category = {}
        group_provider = {}

        for key in sorted(self._shadow_hints_data.keys()):
            parts = key.split("/")
            if parts[0] in KNOWN_PROVIDERS:
                group_provider.setdefault(parts[0], []).append(key)
            elif key == "default":
                group_default[key] = True
            elif key in KNOWN_ANGLES:
                group_angle[key] = True
            elif key in KNOWN_TYPES and key not in KNOWN_ANGLES:
                group_angle[key] = True
            elif "/" in key:
                cat = parts[0]
                group_category.setdefault(cat, []).append(key)
            else:
                group_category.setdefault(key, []).append(key)

        font_bold = QFont(FONT_FAMILY, 10)
        font_bold.setBold(True)
        font_cat = QFont(FONT_FAMILY, 9)
        font_cat.setBold(True)
        font_prov = QFont(FONT_FAMILY, 9)
        font_prov.setBold(True)
        font_leaf = QFont(FONT_FAMILY, 9)

        color_cat = QColor("#7c3aed")
        color_prov = QColor("#0891b2")

        # Default
        if group_default:
            node_def = QTreeWidgetItem(tree, ["기본 (default)", ""])
            node_def.setFont(0, font_bold)
            node_def.setExpanded(True)
            for k in group_default:
                preview = self._shadow_hints_data[k][:50].replace("\n", " ")
                item = QTreeWidgetItem(node_def, [k, preview])
                item.setFont(0, font_leaf)
                item.setData(0, Qt.UserRole, k)

        # Angles
        if group_angle:
            node_angle = QTreeWidgetItem(tree, ["촬영방향별", ""])
            node_angle.setFont(0, font_bold)
            node_angle.setExpanded(True)
            for k in sorted(group_angle.keys()):
                preview = self._shadow_hints_data[k][:50].replace("\n", " ")
                item = QTreeWidgetItem(node_angle, [k, preview])
                item.setFont(0, font_leaf)
                item.setData(0, Qt.UserRole, k)

        # Categories
        if group_category:
            node_cat = QTreeWidgetItem(tree, ["카테고리별", ""])
            node_cat.setFont(0, font_bold)
            node_cat.setExpanded(True)
            for cat in sorted(group_category.keys()):
                keys = sorted(group_category[cat])
                cat_node = QTreeWidgetItem(node_cat, [cat, ""])
                cat_node.setFont(0, font_cat)
                cat_node.setForeground(0, color_cat)
                cat_node.setExpanded(True)
                for k in keys:
                    parts = k.split("/")
                    display = "(기본)" if len(parts) == 1 else "/".join(parts[1:])
                    preview = self._shadow_hints_data[k][:50].replace("\n", " ")
                    item = QTreeWidgetItem(cat_node, [display, preview])
                    item.setFont(0, font_leaf)
                    item.setData(0, Qt.UserRole, k)

        # Providers
        if group_provider:
            node_prov = QTreeWidgetItem(tree, ["Provider별", ""])
            node_prov.setFont(0, font_bold)
            node_prov.setExpanded(False)
            for prov in sorted(group_provider.keys()):
                keys = sorted(group_provider[prov])
                prov_node = QTreeWidgetItem(node_prov, [prov, ""])
                prov_node.setFont(0, font_prov)
                prov_node.setForeground(0, color_prov)
                prov_node.setExpanded(True)
                for k in keys:
                    parts = k.split("/")
                    display = "/".join(parts[1:]) if len(parts) > 1 else k
                    preview = self._shadow_hints_data[k][:50].replace("\n", " ")
                    item = QTreeWidgetItem(prov_node, [display, preview])
                    item.setFont(0, font_leaf)
                    item.setData(0, Qt.UserRole, k)

    def _save_shadow_hints(self):
        try:
            save_yaml(SHADOW_HINTS_PATH, self._shadow_hints_data)
            self._show_status("힌트 파일 저장 완료", SUCCESS)
        except Exception as e:
            self._show_status(f"저장 실패: {e}", DANGER)

    def on_hint_edit_save(self):
        key = self._current_hint_key
        if not key:
            self._show_status("저장할 힌트를 선택하세요", DANGER)
            return
        text = self.txt_hint_editor.toPlainText().strip()
        self._shadow_hints_data[key] = text
        # Update preview in tree
        current = self.hint_tree.currentItem()
        if current and current.data(0, Qt.UserRole) == key:
            preview = text[:50].replace("\n", " ")
            current.setText(1, preview)
        self._save_shadow_hints()

    def on_hint_add(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("새 그림자 힌트 추가")
        dlg.setFixedSize(420, 340)
        layout = QVBoxLayout(dlg)

        title_lbl = QLabel("새 힌트 키 구성")
        title_lbl.setStyleSheet(f"font-size: 11pt; font-weight: bold; font-family: '{FONT_FAMILY}';")
        layout.addWidget(title_lbl)

        # Provider
        prov_row = QHBoxLayout()
        prov_row.addWidget(QLabel("Provider (선택):"))
        cb_prov = QComboBox()
        cb_prov.addItems(["(공통)", "gemini_shadow", "grok_shadow"])
        prov_row.addWidget(cb_prov)
        prov_row.addStretch()
        layout.addLayout(prov_row)

        # Category
        cat_row = QHBoxLayout()
        cat_row.addWidget(QLabel("카테고리:"))
        cb_cat = QComboBox()
        cb_cat.setEditable(True)
        cb_cat.addItems(["(없음)", "bag", "shoes", "clothing", "hat", "accessory",
                         "watch", "jewelry", "wallet", "belt", "scarf", "sunglasses", "other"])
        cat_row.addWidget(cb_cat)
        lbl_cat_hint = QLabel("또는 직접 입력")
        lbl_cat_hint.setStyleSheet("font-size: 8pt; color: #9ca3af;")
        cat_row.addWidget(lbl_cat_hint)
        cat_row.addStretch()
        layout.addLayout(cat_row)

        # Angle
        angle_row = QHBoxLayout()
        angle_row.addWidget(QLabel("촬영방향:"))
        cb_angle = QComboBox()
        cb_angle.addItems(["(없음)", "front", "high_angle", "top_down", "side",
                           "detail", "held", "worn"])
        angle_row.addWidget(cb_angle)
        angle_row.addStretch()
        layout.addLayout(angle_row)

        # Type
        type_row = QHBoxLayout()
        type_row.addWidget(QLabel("촬영유형:"))
        cb_type = QComboBox()
        cb_type.addItems(["(없음)", "full", "detail", "worn", "package"])
        type_row.addWidget(cb_type)
        type_row.addStretch()
        layout.addLayout(type_row)

        # Direct key
        sep = QLabel("")
        sep.setFixedHeight(8)
        layout.addWidget(sep)
        direct_row = QHBoxLayout()
        direct_row.addWidget(QLabel("또는 직접 키 입력:"))
        ent_direct = QLineEdit()
        direct_row.addWidget(ent_direct)
        layout.addLayout(direct_row)

        # Preview
        lbl_preview = QLabel("키: (선택하세요)")
        lbl_preview.setStyleSheet(
            f"font-size: 10pt; font-weight: bold; color: {ACCENT}; font-family: '{FONT_FAMILY}';")
        layout.addWidget(lbl_preview)

        def _update_preview():
            direct = ent_direct.text().strip()
            if direct:
                lbl_preview.setText(f"키: {direct}")
                return
            parts = []
            prov = cb_prov.currentText()
            if prov and prov != "(공통)":
                parts.append(prov)
            cat = cb_cat.currentText()
            if cat and cat != "(없음)":
                parts.append(cat)
            angle = cb_angle.currentText()
            if angle and angle != "(없음)":
                parts.append(angle)
            itype = cb_type.currentText()
            if itype and itype != "(없음)":
                parts.append(itype)
            key = "/".join(parts) if parts else "(선택하세요)"
            lbl_preview.setText(f"키: {key}")

        cb_prov.currentTextChanged.connect(lambda: _update_preview())
        cb_cat.currentTextChanged.connect(lambda: _update_preview())
        cb_angle.currentTextChanged.connect(lambda: _update_preview())
        cb_type.currentTextChanged.connect(lambda: _update_preview())
        ent_direct.textChanged.connect(lambda: _update_preview())

        # Buttons
        btn_row = QHBoxLayout()
        btn_ok = QPushButton("추가")
        btn_ok.setProperty("cssClass", "accent")
        btn_cancel = QPushButton("취소")

        def _on_ok():
            direct = ent_direct.text().strip()
            if direct:
                key = direct
            else:
                parts = []
                prov = cb_prov.currentText()
                if prov and prov != "(공통)":
                    parts.append(prov)
                cat = cb_cat.currentText()
                if cat and cat != "(없음)":
                    parts.append(cat)
                angle = cb_angle.currentText()
                if angle and angle != "(없음)":
                    parts.append(angle)
                itype = cb_type.currentText()
                if itype and itype != "(없음)":
                    parts.append(itype)
                key = "/".join(parts)
            if not key:
                QMessageBox.warning(dlg, "입력 오류", "키를 구성하세요.")
                return
            if key in self._shadow_hints_data:
                QMessageBox.warning(dlg, "중복", f"이미 존재하는 키입니다: {key}")
                return
            self._shadow_hints_data[key] = ""
            self.rebuild_hint_tree()
            self._select_tree_key(key)
            self._show_status(f"'{key}' 추가됨 -- 내용 입력 후 [저장]", SUCCESS)
            dlg.accept()

        btn_ok.clicked.connect(_on_ok)
        btn_cancel.clicked.connect(dlg.reject)
        btn_row.addWidget(btn_ok)
        btn_row.addWidget(btn_cancel)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        dlg.exec()

    def on_hint_delete(self):
        key = self._current_hint_key
        if not key:
            self._show_status("삭제할 힌트를 선택하세요", DANGER)
            return
        if key == "default":
            QMessageBox.warning(self, "삭제 불가", "기본(default) 힌트는 삭제할 수 없습니다.")
            return
        reply = QMessageBox.question(
            self, "삭제 확인", f"'{key}' 힌트를 삭제하시겠습니까?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        self._shadow_hints_data.pop(key, None)
        self._current_hint_key = None
        self.lbl_hint_key.setText("(선택 없음)")
        self.txt_hint_editor.clear()
        self.rebuild_hint_tree()
        self._save_shadow_hints()
        self._show_status(f"'{key}' 삭제됨", SUCCESS)

    def _select_tree_key(self, key):
        """Find and select the tree item with the given key."""
        def _search(parent_item):
            for i in range(parent_item.childCount()):
                child = parent_item.child(i)
                if child.data(0, Qt.UserRole) == key:
                    self.hint_tree.setCurrentItem(child)
                    self.hint_tree.scrollToItem(child)
                    return True
                if _search(child):
                    return True
            return False

        for i in range(self.hint_tree.topLevelItemCount()):
            top = self.hint_tree.topLevelItem(i)
            if _search(top):
                break

    def _show_status(self, msg, color=None):
        style = f"font-family: '{FONT_FAMILY}';"
        if color:
            style += f" color: {color};"
        self.lbl_status.setStyleSheet(style)
        self.lbl_status.setText(msg)
        QTimer.singleShot(3000, lambda: self.lbl_status.setText(""))
