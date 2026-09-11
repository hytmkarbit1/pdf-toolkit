import sys
import pymupdf
sys.modules.setdefault("fitz", pymupdf)   # Prevents the deprecated fitz shim from ever loading

import os
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QListWidget, QListWidgetItem, QLabel, QFileDialog, QMessageBox,
    QTabWidget, QRadioButton, QLineEdit, QSpinBox, QComboBox,
    QButtonGroup, QProgressBar, QFrame
)
from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QIcon, QPixmap

import pdf_core
from workers import Worker, ThumbnailWorker


# ---------------------------------------------------------
# Helper: build a QIcon thumbnail from a PDF's first page
# ---------------------------------------------------------
def make_pdf_icon(pdf_path, max_dim=140):
    try:
        data = pdf_core.render_page_thumbnail(pdf_path, 0, max_dim)
        pix = QPixmap()
        pix.loadFromData(data)
        return QIcon(pix)
    except Exception:
        return QIcon()  # Blank icon fallback if the file can't be previewed


# ---------------------------------------------------------
# Reusable drag & drop widgets
# ---------------------------------------------------------
class DropListWidget(QListWidget):
    def __init__(self, file_filter_ext=(".pdf",), show_thumbnails=False):
        super().__init__()
        self.setAcceptDrops(True)
        self.file_filter_ext = file_filter_ext
        self.show_thumbnails = show_thumbnails
        if show_thumbnails:
            self.setViewMode(QListWidget.IconMode)
            self.setIconSize(QSize(110, 140))
            self.setResizeMode(QListWidget.Adjust)
            self.setMovement(QListWidget.Static)
            self.setSpacing(12)
            self.setWordWrap(True)

    def add_pdf_item(self, path):
        item = QListWidgetItem(os.path.basename(path))
        item.setData(Qt.UserRole, path)
        if self.show_thumbnails:
            item.setIcon(make_pdf_icon(path))
            item.setTextAlignment(Qt.AlignHCenter)
        self.addItem(item)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith(self.file_filter_ext):
                self.add_pdf_item(path)


class DropLineEdit(QLineEdit):
    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setPlaceholderText("Drag & drop a PDF here, or click Browse")

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if path.lower().endswith(".pdf"):
                self.setText(path)


def make_card(widget):
    """Wraps a widget in a rounded white 'card' container."""
    card = QFrame()
    card.setObjectName("Card")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(20, 20, 20, 20)
    layout.addWidget(widget)
    return card


# ---------------------------------------------------------
# MERGE TAB
# ---------------------------------------------------------
class MergeTab(QWidget):
    def __init__(self):
        super().__init__()
        self.worker = None
        outer = QVBoxLayout(self)
        outer.setSpacing(14)
        outer.setContentsMargins(4, 4, 4, 4)

        title = QLabel("Merge PDFs")
        title.setObjectName("Title")
        subtitle = QLabel("Drag files below, reorder them, then combine into one PDF.")
        subtitle.setObjectName("Subtitle")
        outer.addWidget(title)
        outer.addWidget(subtitle)

        # Thumbnail grid — each item shows a snippet of the file's first page
        self.file_list = DropListWidget(show_thumbnails=True)
        self.file_list.setObjectName("PdfFileList")
        outer.addWidget(self.file_list, stretch=1)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("Add PDFs")
        remove_btn = QPushButton("Remove Selected")
        remove_btn.setObjectName("SecondaryButton")
        up_btn = QPushButton("↑ Up")
        up_btn.setObjectName("SecondaryButton")
        down_btn = QPushButton("↓ Down")
        down_btn.setObjectName("SecondaryButton")

        add_btn.clicked.connect(self.add_files)
        remove_btn.clicked.connect(self.remove_selected)
        up_btn.clicked.connect(lambda: self.move_item(-1))
        down_btn.clicked.connect(lambda: self.move_item(1))

        for b in (add_btn, remove_btn, up_btn, down_btn):
            btn_row.addWidget(b)
        outer.addLayout(btn_row)

        self.progress = QProgressBar()
        self.progress.setValue(0)
        outer.addWidget(self.progress)

        self.status_label = QLabel("")
        self.status_label.setObjectName("StatusLabel")
        outer.addWidget(self.status_label)

        self.merge_btn = QPushButton("Merge PDFs")
        self.merge_btn.clicked.connect(self.do_merge)
        outer.addWidget(self.merge_btn)

        outer.addStretch()

    def add_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Select PDFs", "", "PDF Files (*.pdf)")
        for f in files:
            self.file_list.add_pdf_item(f)

    def remove_selected(self):
        for item in self.file_list.selectedItems():
            self.file_list.takeItem(self.file_list.row(item))

    def move_item(self, direction):
        row = self.file_list.currentRow()
        if row < 0:
            return
        new_row = row + direction
        if 0 <= new_row < self.file_list.count():
            item = self.file_list.takeItem(row)
            self.file_list.insertItem(new_row, item)
            self.file_list.setCurrentRow(new_row)

    def do_merge(self):
        files = [self.file_list.item(i).data(Qt.UserRole) for i in range(self.file_list.count())]
        if len(files) < 2:
            QMessageBox.warning(self, "Need more files", "Add at least 2 PDFs to merge.")
            return
        output, _ = QFileDialog.getSaveFileName(self, "Save merged PDF", "merged.pdf", "PDF Files (*.pdf)")
        if not output:
            return

        self.merge_btn.setEnabled(False)
        self.status_label.setText("Merging...")
        self.progress.setRange(0, 100)
        self.progress.setValue(0)

        self.worker = Worker(pdf_core.merge_pdfs, files, output)
        self.worker.progress.connect(self.on_progress)
        self.worker.finished.connect(self.on_finished)
        self.worker.error.connect(self.on_error)
        self.worker.start()

    def on_progress(self, value):
        if value == -1:
            self.progress.setRange(0, 0)
        else:
            self.progress.setRange(0, 100)
            self.progress.setValue(value)

    def on_finished(self, result):
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.status_label.setText("Done!")
        self.merge_btn.setEnabled(True)
        QMessageBox.information(self, "Done", f"Merged PDF saved to:\n{result}")

    def on_error(self, message):
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.status_label.setText("Failed.")
        self.merge_btn.setEnabled(True)
        QMessageBox.critical(self, "Error", message)


# ---------------------------------------------------------
# SPLIT TAB
# ---------------------------------------------------------
class SplitTab(QWidget):
    def __init__(self):
        super().__init__()
        self.worker = None
        self.thumb_worker = None
        self._thumb_gen = 0
        outer = QVBoxLayout(self)
        outer.setSpacing(14)
        outer.setContentsMargins(4, 4, 4, 4)

        title = QLabel("Split PDF")
        title.setObjectName("Title")
        subtitle = QLabel("Break one PDF into multiple files.")
        subtitle.setObjectName("Subtitle")
        outer.addWidget(title)
        outer.addWidget(subtitle)

        file_row = QHBoxLayout()
        self.file_path = DropLineEdit()
        browse_btn = QPushButton("Browse")
        browse_btn.setObjectName("SecondaryButton")
        browse_btn.clicked.connect(self.browse_file)
        self.file_path.textChanged.connect(self.on_file_changed)
        file_row.addWidget(self.file_path, stretch=1)
        file_row.addWidget(browse_btn)
        outer.addLayout(file_row)

        preview_label = QLabel("Preview (click pages to build a custom range):")
        outer.addWidget(preview_label)

        # Thumbnail grid — every page of the loaded PDF, selectable for custom ranges
        self.thumb_list = QListWidget()
        self.thumb_list.setObjectName("ThumbList")
        self.thumb_list.setViewMode(QListWidget.IconMode)
        self.thumb_list.setFlow(QListWidget.LeftToRight)
        self.thumb_list.setWrapping(True)
        self.thumb_list.setIconSize(QSize(90, 120))
        self.thumb_list.setResizeMode(QListWidget.Adjust)
        self.thumb_list.setMovement(QListWidget.Static)
        self.thumb_list.setSpacing(8)
        self.thumb_list.setSelectionMode(QListWidget.ExtendedSelection)
        self.thumb_list.setMinimumHeight(160)
        self.thumb_list.itemSelectionChanged.connect(self.on_thumb_selection_changed)
        outer.addWidget(self.thumb_list, stretch=1)

        self.radio_all = QRadioButton("Split into individual pages")
        self.radio_n = QRadioButton("Split every N pages")
        self.radio_range = QRadioButton("Custom page range (e.g. 1-3,5,7-9)")
        self.radio_all.setChecked(True)
        group = QButtonGroup(self)
        for r in (self.radio_all, self.radio_n, self.radio_range):
            group.addButton(r)
            outer.addWidget(r)

        n_row = QHBoxLayout()
        n_row.addWidget(QLabel("N ="))
        self.n_spin = QSpinBox()
        self.n_spin.setRange(1, 9999)
        self.n_spin.setValue(2)
        n_row.addWidget(self.n_spin)
        n_row.addStretch()
        outer.addLayout(n_row)

        self.range_input = QLineEdit()
        self.range_input.setPlaceholderText("e.g. 1-3,5,7-9")
        outer.addWidget(self.range_input)

        self.progress = QProgressBar()
        self.progress.setValue(0)
        outer.addWidget(self.progress)

        self.status_label = QLabel("")
        self.status_label.setObjectName("StatusLabel")
        outer.addWidget(self.status_label)

        self.split_btn = QPushButton("Split PDF")
        self.split_btn.clicked.connect(self.do_split)
        outer.addWidget(self.split_btn)

        outer.addStretch()

    # --- thumbnail preview logic ---
    def on_file_changed(self, text):
        text = text.strip()
        if text and os.path.exists(text) and text.lower().endswith(".pdf"):
            self.load_thumbnails(text)
        else:
            self.thumb_list.clear()

    def load_thumbnails(self, pdf_path):
        self.thumb_list.clear()
        self._thumb_gen += 1
        gen = self._thumb_gen

        self.thumb_worker = ThumbnailWorker(pdf_path)
        self.thumb_worker.thumbnail_ready.connect(
            lambda idx, data, g=gen: self.add_thumbnail(idx, data, g)
        )
        self.thumb_worker.start()

    def add_thumbnail(self, page_index, png_bytes, gen):
        if gen != self._thumb_gen:
            return  # Stale result from a previously loaded file — ignore it
        pix = QPixmap()
        pix.loadFromData(png_bytes)
        item = QListWidgetItem(QIcon(pix), f"Page {page_index + 1}")
        item.setData(Qt.UserRole, page_index)
        item.setTextAlignment(Qt.AlignHCenter)
        self.thumb_list.addItem(item)

    def on_thumb_selection_changed(self):
        selected = sorted(item.data(Qt.UserRole) for item in self.thumb_list.selectedItems())
        if not selected:
            return
        # Clicking thumbnails auto-builds a compact range string, e.g. "1-3,5,7-9"
        self.radio_range.setChecked(True)
        ranges = []
        start = prev = selected[0]
        for p in selected[1:]:
            if p == prev + 1:
                prev = p
                continue
            ranges.append(f"{start + 1}-{prev + 1}" if start != prev else f"{start + 1}")
            start = prev = p
        ranges.append(f"{start + 1}-{prev + 1}" if start != prev else f"{start + 1}")
        self.range_input.setText(",".join(ranges))

    def browse_file(self):
        f, _ = QFileDialog.getOpenFileName(self, "Select PDF", "", "PDF Files (*.pdf)")
        if f:
            self.file_path.setText(f)

    def do_split(self):
        pdf_path = self.file_path.text().strip()
        if not pdf_path or not os.path.exists(pdf_path):
            QMessageBox.warning(self, "No file", "Please select a valid PDF file.")
            return
        output_dir = QFileDialog.getExistingDirectory(self, "Choose output folder")
        if not output_dir:
            return

        self.split_btn.setEnabled(False)
        self.status_label.setText("Splitting...")
        self.progress.setRange(0, 100)
        self.progress.setValue(0)

        if self.radio_all.isChecked():
            self.worker = Worker(pdf_core.split_all_pages, pdf_path, output_dir)
        elif self.radio_n.isChecked():
            self.worker = Worker(pdf_core.split_every_n_pages, pdf_path, output_dir, self.n_spin.value())
        else:
            self.worker = Worker(pdf_core.split_by_ranges, pdf_path, output_dir, self.range_input.text())

        self.worker.progress.connect(self.on_progress)
        self.worker.finished.connect(self.on_finished)
        self.worker.error.connect(self.on_error)
        self.worker.start()

    def on_progress(self, value):
        if value == -1:
            self.progress.setRange(0, 0)
        else:
            self.progress.setRange(0, 100)
            self.progress.setValue(value)

    def on_finished(self, result):
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.status_label.setText("Done!")
        self.split_btn.setEnabled(True)
        QMessageBox.information(self, "Done", f"Created {len(result)} file(s).")

    def on_error(self, message):
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.status_label.setText("Failed.")
        self.split_btn.setEnabled(True)
        QMessageBox.critical(self, "Error", message)


# ---------------------------------------------------------
# CONVERT TAB
# ---------------------------------------------------------
class ConvertTab(QWidget):
    def __init__(self):
        super().__init__()
        self.worker = None
        self.sim_timer = QTimer()
        self.sim_timer.timeout.connect(self.tick_simulated_progress)
        self.sim_value = 0

        outer = QVBoxLayout(self)
        outer.setSpacing(14)
        outer.setContentsMargins(4, 4, 4, 4)

        title = QLabel("Convert PDF")
        title.setObjectName("Title")
        subtitle = QLabel("Turn your PDF into DOCX, images, or Markdown.")
        subtitle.setObjectName("Subtitle")
        outer.addWidget(title)
        outer.addWidget(subtitle)

        file_row = QHBoxLayout()
        self.file_path = DropLineEdit()
        browse_btn = QPushButton("Browse")
        browse_btn.setObjectName("SecondaryButton")
        browse_btn.clicked.connect(self.browse_file)
        file_row.addWidget(self.file_path, stretch=1)
        file_row.addWidget(browse_btn)
        outer.addLayout(file_row)

        outer.addWidget(QLabel("Convert to:"))
        self.format_box = QComboBox()
        self.format_box.addItems(["DOCX", "PNG Images", "JPG Images", "Markdown"])
        outer.addWidget(self.format_box)

        dpi_row = QHBoxLayout()
        dpi_row.addWidget(QLabel("Image DPI (for image export):"))
        self.dpi_spin = QSpinBox()
        self.dpi_spin.setRange(72, 600)
        self.dpi_spin.setValue(200)
        dpi_row.addWidget(self.dpi_spin)
        dpi_row.addStretch()
        outer.addLayout(dpi_row)

        self.progress = QProgressBar()
        self.progress.setValue(0)
        outer.addWidget(self.progress)

        self.status_label = QLabel("")
        self.status_label.setObjectName("StatusLabel")
        outer.addWidget(self.status_label)

        self.convert_btn = QPushButton("Convert")
        self.convert_btn.clicked.connect(self.do_convert)
        outer.addWidget(self.convert_btn)

        outer.addStretch()

    # --- simulated progress helpers (for DOCX / Markdown, which have no real % signal) ---
    def start_simulated_progress(self):
        self.sim_value = 0
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.sim_timer.start(100)

    def tick_simulated_progress(self):
        remaining = 95 - self.sim_value
        step = max(1, int(remaining * 0.06))
        self.sim_value = min(95, self.sim_value + step)
        self.progress.setValue(self.sim_value)

    def stop_simulated_progress(self):
        self.sim_timer.stop()

    def browse_file(self):
        f, _ = QFileDialog.getOpenFileName(self, "Select PDF", "", "PDF Files (*.pdf)")
        if f:
            self.file_path.setText(f)

    def do_convert(self):
        pdf_path = self.file_path.text().strip()
        if not pdf_path or not os.path.exists(pdf_path):
            QMessageBox.warning(self, "No file", "Please select a valid PDF file.")
            return

        fmt = self.format_box.currentText()
        base = os.path.splitext(os.path.basename(pdf_path))[0]

        if fmt == "DOCX":
            output, _ = QFileDialog.getSaveFileName(self, "Save DOCX", f"{base}.docx", "Word Files (*.docx)")
            if not output:
                return
            self.worker = Worker(pdf_core.pdf_to_docx, pdf_path, output)

        elif fmt in ("PNG Images", "JPG Images"):
            output_dir = QFileDialog.getExistingDirectory(self, "Choose output folder")
            if not output_dir:
                return
            img_format = "png" if fmt == "PNG Images" else "jpg"
            self.worker = Worker(pdf_core.pdf_to_images, pdf_path, output_dir, img_format, self.dpi_spin.value())

        elif fmt == "Markdown":
            output, _ = QFileDialog.getSaveFileName(self, "Save Markdown", f"{base}.md", "Markdown Files (*.md)")
            if not output:
                return
            self.worker = Worker(pdf_core.pdf_to_markdown, pdf_path, output)

        self.convert_btn.setEnabled(False)
        self.status_label.setText("Converting... this may take a moment for large files.")
        self.progress.setRange(0, 100)
        self.progress.setValue(0)

        self.worker.progress.connect(self.on_progress)
        self.worker.finished.connect(self.on_finished)
        self.worker.error.connect(self.on_error)
        self.worker.start()

    def on_progress(self, value):
        if value == -1:
            self.start_simulated_progress()
        else:
            self.stop_simulated_progress()
            self.progress.setRange(0, 100)
            self.progress.setValue(value)

    def on_finished(self, result):
        self.stop_simulated_progress()
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.status_label.setText("Done!")
        self.convert_btn.setEnabled(True)
        if isinstance(result, list):
            QMessageBox.information(self, "Done", f"Created {len(result)} file(s).")
        else:
            QMessageBox.information(self, "Done", f"Saved to:\n{result}")

    def on_error(self, message):
        self.stop_simulated_progress()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.status_label.setText("Failed.")
        self.convert_btn.setEnabled(True)
        QMessageBox.critical(self, "Error", message)


# ---------------------------------------------------------
# MAIN WINDOW
# ---------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF Toolkit")
        self.resize(680, 640)

        tabs = QTabWidget()
        tabs.addTab(make_card(MergeTab()), "Merge")
        tabs.addTab(make_card(SplitTab()), "Split")
        tabs.addTab(make_card(ConvertTab()), "Convert")
        self.setCentralWidget(tabs)


def load_stylesheet(app):
    if hasattr(sys, "_MEIPASS"):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
    style_path = os.path.join(base_path, "style.qss")
    if os.path.exists(style_path):
        with open(style_path, "r", encoding="utf-8") as f:
            app.setStyleSheet(f.read())


if __name__ == "__main__":
    app = QApplication(sys.argv)
    load_stylesheet(app)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
