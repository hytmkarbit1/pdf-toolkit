from PySide6.QtCore import QThread, Signal


class Worker(QThread):
    """Runs any pdf_core function on a background thread.
    Expects the target function to accept a `progress_callback` kwarg.
    """
    progress = Signal(int)      # 0-100, or -1 for "indeterminate / busy"
    finished = Signal(object)   # whatever the function returns
    error = Signal(str)

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs

    def run(self):
        try:
            result = self.fn(*self.args, progress_callback=self.progress.emit, **self.kwargs)
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


class ThumbnailWorker(QThread):
    """Renders every page of a PDF as a small PNG thumbnail, emitting each one
    as soon as it's ready so the UI can populate the preview grid progressively
    instead of freezing while a large PDF is fully processed.
    """
    thumbnail_ready = Signal(int, bytes)   # page_index, PNG bytes
    error = Signal(str)

    def __init__(self, pdf_path, max_dim=140):
        super().__init__()
        self.pdf_path = pdf_path
        self.max_dim = max_dim

    def run(self):
        try:
            import pymupdf as fitz
            doc = fitz.open(self.pdf_path)
            for i, page in enumerate(doc):
                rect = page.rect
                scale = self.max_dim / max(rect.width, rect.height)
                matrix = fitz.Matrix(scale, scale)
                pix = page.get_pixmap(matrix=matrix)
                data = pix.tobytes("png")
                self.thumbnail_ready.emit(i, data)
            doc.close()
        except Exception as e:
            self.error.emit(str(e))
