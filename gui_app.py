import sys
import os
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QLineEdit, QComboBox, QSlider, QPushButton, QFileDialog,
                             QMessageBox, QSpinBox, QProgressBar, QSplitter, QFrame, QGroupBox)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure
from backend import MapGenerator
import matplotlib.pyplot as plt

# Worker Thread for fetching data (Network heavy)
class DataFetchThread(QThread):
    progress_signal = pyqtSignal(str, float)
    finished_signal = pyqtSignal(object, tuple, str, str) # data, point, city, country
    error_signal = pyqtSignal(str)

    def __init__(self, generator, city, country, distance):
        super().__init__()
        self.generator = generator
        self.city = city
        self.country = country
        self.distance = distance

    def run(self):
        try:
            self.progress_signal.emit("Locating city...", 0.05)
            point = self.generator.get_coordinates(self.city, self.country)

            def callback(msg, prog):
                # Scale progress to 0.1 - 0.9 range
                self.progress_signal.emit(msg, 0.1 + (prog * 0.8))

            data = self.generator.fetch_data(point, self.distance, callback=callback)

            self.progress_signal.emit("Data fetch complete", 1.0)
            self.finished_signal.emit(data, point, self.city, self.country)

        except Exception as e:
            self.error_signal.emit(str(e))

# Worker Thread for rendering map (CPU heavy)
class RenderThread(QThread):
    finished_signal = pyqtSignal(object) # figure
    error_signal = pyqtSignal(str)

    def __init__(self, generator, data, theme_name, city, country, point):
        super().__init__()
        self.generator = generator
        self.data = data
        self.theme_name = theme_name
        self.city = city
        self.country = country
        self.point = point

    def run(self):
        try:
            theme = self.generator.load_theme(self.theme_name)
            # Render map returns a matplotlib figure
            # We need to make sure we are thread safe with matplotlib?
            # Usually creating figure is fine, drawing to canvas needs main thread.
            # But MapGenerator.render_map creates a new figure with plt.subplots.
            # We should probably avoid using pyplot's global state interface in threads if possible,
            # but MapGenerator uses plt.subplots.
            # It's better if MapGenerator used Figure() directly, but let's see.
            # Actually, plt.subplots is not thread safe if using the global state backend.
            # However, backend logic just creates a figure.

            fig = self.generator.render_map(self.data, theme, self.city, self.country, self.point)
            self.finished_signal.emit(fig)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.error_signal.emit(str(e))

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("City Map Poster Generator")
        self.resize(1200, 800)

        self.generator = MapGenerator()

        # State
        self.current_data = None
        self.current_point = None
        self.current_city = ""
        self.current_country = ""
        self.current_theme = "feature_based"
        self.preview_fig = None

        # Main Layout
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QHBoxLayout(main_widget)

        # Splitter for resizable sidebar
        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter)

        # --- Left Sidebar ---
        sidebar = QWidget()
        sidebar.setMinimumWidth(300)
        sidebar.setMaximumWidth(400)
        sidebar_layout = QVBoxLayout(sidebar)

        # Controls Group
        controls_group = QGroupBox("Map Settings")
        controls_layout = QVBoxLayout()

        # City
        controls_layout.addWidget(QLabel("City:"))
        self.city_input = QLineEdit()
        self.city_input.setPlaceholderText("e.g. New York")
        controls_layout.addWidget(self.city_input)

        # Country
        controls_layout.addWidget(QLabel("Country:"))
        self.country_input = QLineEdit()
        self.country_input.setPlaceholderText("e.g. USA")
        controls_layout.addWidget(self.country_input)

        # Theme
        controls_layout.addWidget(QLabel("Theme:"))
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(self.generator.get_available_themes())
        self.theme_combo.setCurrentText(self.current_theme)
        self.theme_combo.currentTextChanged.connect(self.on_theme_changed)
        controls_layout.addWidget(self.theme_combo)

        # Distance (Radius)
        controls_layout.addWidget(QLabel("Radius (meters):"))
        dist_layout = QHBoxLayout()
        self.dist_slider = QSlider(Qt.Orientation.Horizontal)
        self.dist_slider.setRange(1000, 50000)
        self.dist_slider.setValue(29000)
        self.dist_spin = QSpinBox()
        self.dist_spin.setRange(1000, 50000)
        self.dist_spin.setValue(29000)
        self.dist_spin.setSingleStep(1000)

        # Connect slider and spinbox
        self.dist_slider.valueChanged.connect(self.dist_spin.setValue)
        self.dist_spin.valueChanged.connect(self.dist_slider.setValue)

        dist_layout.addWidget(self.dist_slider)
        dist_layout.addWidget(self.dist_spin)
        controls_layout.addLayout(dist_layout)

        # Generate Button
        self.generate_btn = QPushButton("Generate Preview")
        self.generate_btn.clicked.connect(self.start_generation)
        self.generate_btn.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold; padding: 10px;")
        controls_layout.addWidget(self.generate_btn)

        controls_group.setLayout(controls_layout)
        sidebar_layout.addWidget(controls_group)

        # Export Group
        export_group = QGroupBox("Export Settings")
        export_layout = QVBoxLayout()

        export_layout.addWidget(QLabel("DPI:"))
        self.dpi_spin = QSpinBox()
        self.dpi_spin.setRange(72, 1200)
        self.dpi_spin.setValue(300)
        export_layout.addWidget(self.dpi_spin)

        self.export_btn = QPushButton("Export High-Res Poster")
        self.export_btn.clicked.connect(self.export_poster)
        self.export_btn.setEnabled(False) # Disabled until map is generated
        export_layout.addWidget(self.export_btn)

        export_group.setLayout(export_layout)
        sidebar_layout.addWidget(export_group)

        # Progress Bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        sidebar_layout.addWidget(self.progress_bar)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        sidebar_layout.addWidget(self.status_label)

        sidebar_layout.addStretch()

        # --- Center Preview ---
        preview_container = QWidget()
        preview_layout = QVBoxLayout(preview_container)

        # We start with a placeholder or empty canvas
        self.figure = Figure()
        self.canvas = FigureCanvas(self.figure)

        # Add Navigation Toolbar for Pan/Zoom
        self.toolbar = NavigationToolbar(self.canvas, self)

        preview_layout.addWidget(self.toolbar)
        preview_layout.addWidget(self.canvas)

        # Add widgets to splitter
        splitter.addWidget(sidebar)
        splitter.addWidget(preview_container)
        splitter.setStretchFactor(1, 4) # Give more space to preview

    def start_generation(self):
        city = self.city_input.text().strip()
        country = self.country_input.text().strip()
        distance = self.dist_spin.value()

        if not city or not country:
            QMessageBox.warning(self, "Input Error", "Please enter both City and Country.")
            return

        self.generate_btn.setEnabled(False)
        self.export_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.status_label.setText("Starting...")

        # Start Data Fetch Thread
        self.fetch_thread = DataFetchThread(self.generator, city, country, distance)
        self.fetch_thread.progress_signal.connect(self.update_progress)
        self.fetch_thread.finished_signal.connect(self.on_data_fetched)
        self.fetch_thread.error_signal.connect(self.on_error)
        self.fetch_thread.start()

    def update_progress(self, msg, value):
        self.status_label.setText(msg)
        self.progress_bar.setValue(int(value * 100))

    def on_error(self, msg):
        self.generate_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.status_label.setText(f"Error: {msg}")
        QMessageBox.critical(self, "Error", msg)

    def on_data_fetched(self, data, point, city, country):
        self.current_data = data
        self.current_point = point
        self.current_city = city
        self.current_country = country

        # Start Rendering
        self.update_preview()

    def on_theme_changed(self, theme_name):
        self.current_theme = theme_name
        if self.current_data:
            self.update_preview()

    def update_preview(self):
        if not self.current_data:
            return

        self.status_label.setText("Rendering map preview...")
        self.progress_bar.setVisible(True) # Keep showing progress for rendering
        self.progress_bar.setRange(0, 0) # Indeterminate mode for rendering

        self.render_thread = RenderThread(
            self.generator,
            self.current_data,
            self.current_theme,
            self.current_city,
            self.current_country,
            self.current_point
        )
        self.render_thread.finished_signal.connect(self.on_render_finished)
        self.render_thread.error_signal.connect(self.on_error)
        self.render_thread.start()

    def on_render_finished(self, fig):
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setVisible(False)
        self.status_label.setText("Render complete.")
        self.generate_btn.setEnabled(True)
        self.export_btn.setEnabled(True)

        # Update Canvas
        # We need to replace the figure in the canvas
        # But FigureCanvasQTAgg.draw() is standard.
        # However, we generated a NEW figure in the thread.
        # Replacing self.canvas.figure might work, but usually it's better to
        # remove the old canvas and add a new one, or re-plot on the existing figure.
        # Since MapGenerator creates a new Figure, let's swap the canvas content.

        # Clean up old figure to avoid memory leaks
        if self.preview_fig:
            plt.close(self.preview_fig)

        self.preview_fig = fig

        # Setup the new figure in the canvas
        # Option A: Replace the figure instance in the canvas
        # self.canvas.figure = fig
        # self.canvas.draw()

        # Option B: Recreate canvas (safer for matplotlib backends sometimes)
        old_canvas = self.canvas
        self.canvas = FigureCanvas(fig)
        self.canvas.setParent(old_canvas.parent())

        layout = old_canvas.parent().layout()
        layout.replaceWidget(old_canvas, self.canvas)
        old_canvas.deleteLater()

        # Update toolbar
        self.toolbar.setParent(None)
        layout.removeWidget(self.toolbar)
        self.toolbar.deleteLater()

        self.toolbar = NavigationToolbar(self.canvas, self)
        layout.insertWidget(0, self.toolbar)

    def export_poster(self):
        if not self.preview_fig:
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Poster", "", "PNG Files (*.png);;PDF Files (*.pdf);;All Files (*)"
        )

        if file_path:
            try:
                dpi = self.dpi_spin.value()
                self.generator.save_poster(self.preview_fig, file_path, dpi=dpi)
                QMessageBox.information(self, "Success", f"Poster saved to:\n{file_path}")
            except Exception as e:
                QMessageBox.critical(self, "Export Error", str(e))

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
