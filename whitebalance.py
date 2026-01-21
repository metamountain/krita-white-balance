import os
# Force CUDA 0
os.environ["CUDA_VISIBLE_DEVICES"] = "0"

from krita import *
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QSlider, QPushButton, QGroupBox, QMessageBox)
from PyQt5.QtCore import Qt, QTimer, QByteArray, QEvent

class WhiteBalanceDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent or Krita.instance().activeWindow().qwindow())
        self.setWindowTitle("Krita WB (Selection Based)")
        self.setMinimumWidth(400)
        
        # Core Data
        self.doc = Krita.instance().activeDocument()
        if not self.doc: return
        self.node = self.doc.activeNode()
        
        # Full Image Bounds
        bounds = self.doc.bounds()
        self.x, self.y, self.w, self.h = bounds.x(), bounds.y(), bounds.width(), bounds.height()
        
        # Store original data (Reference)
        self.original_data = self.node.pixelData(self.x, self.y, self.w, self.h)
        self.current_preview = QByteArray(self.original_data)
        
        # Mutterer Ratios
        self.base_r = 1.0
        self.base_g = 1.0
        self.base_b = 1.0
        
        self.preview_timer = QTimer()
        self.preview_timer.setSingleShot(True)
        self.preview_timer.timeout.connect(self.apply_transformation)
        
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()
        
        # 1. MODES
        mode_group = QGroupBox("1. Calibration Method")
        m_lay = QVBoxLayout()
        
        self.auto_btn = QPushButton("FULL IMAGE (Auto Gray World)")
        self.auto_btn.setToolTip("Analyzes the whole layer to find a color cast.")
        self.auto_btn.clicked.connect(lambda: self.calculate_ratios(use_selection=False))
        
        self.sel_btn = QPushButton("SELECTION AREA (Use Krita Marquee)")
        self.sel_btn.setToolTip("Draw a selection in Krita first, then click this.")
        self.sel_btn.setStyleSheet("font-weight: bold; height: 40px;")
        self.sel_btn.clicked.connect(lambda: self.calculate_ratios(use_selection=True))
        
        m_lay.addWidget(self.auto_btn)
        m_lay.addWidget(self.sel_btn)
        mode_group.setLayout(m_lay)
        layout.addWidget(mode_group)

        # 2. STRENGTH
        blend_group = QGroupBox("2. Correction Strength")
        b_lay = QVBoxLayout()
        self.strength_label = QLabel("Strength: 100%")
        self.strength_slider = QSlider(Qt.Horizontal)
        self.strength_slider.setRange(0, 100)
        self.strength_slider.setValue(100)
        self.strength_slider.valueChanged.connect(self.update_ui)
        b_lay.addWidget(self.strength_label)
        b_lay.addWidget(self.strength_slider)
        blend_group.setLayout(b_lay)
        layout.addWidget(blend_group)

        # 3. SUPPLEMENTS
        slider_group = QGroupBox("3. Manual Fine-Tuning")
        s_lay = QVBoxLayout()
        self.temp_label = QLabel("Temperature: 0")
        self.temp_slider = QSlider(Qt.Horizontal)
        self.temp_slider.setRange(-100, 100)
        self.temp_slider.valueChanged.connect(self.update_ui)
        
        self.tint_label = QLabel("Tint: 0")
        self.tint_slider = QSlider(Qt.Horizontal)
        self.tint_slider.setRange(-100, 100)
        self.tint_slider.valueChanged.connect(self.update_ui)
        
        s_lay.addWidget(self.temp_label)
        s_lay.addWidget(self.temp_slider)
        s_lay.addWidget(self.tint_label)
        s_lay.addWidget(self.tint_slider)
        slider_group.setLayout(s_lay)
        layout.addWidget(slider_group)

        # 4. HOVER COMPARE
        self.comp_btn = QPushButton("HOVER TO SEE ORIGINAL")
        self.comp_btn.setMinimumHeight(40)
        self.comp_btn.installEventFilter(self)
        layout.addWidget(self.comp_btn)

        # 5. BOTTOM
        btn_lay = QHBoxLayout()
        reset_btn = QPushButton("Reset")
        reset_btn.clicked.connect(self.reset_all)
        ok_btn = QPushButton("Apply")
        ok_btn.clicked.connect(self.accept)
        can_btn = QPushButton("Cancel")
        can_btn.clicked.connect(self.cancel)
        
        btn_lay.addWidget(reset_btn)
        btn_lay.addStretch()
        btn_lay.addWidget(can_btn)
        btn_lay.addWidget(ok_btn)
        layout.addLayout(btn_lay)
        
        self.setLayout(layout)

    def update_ui(self):
        self.strength_label.setText(f"Strength: {self.strength_slider.value()}%")
        self.temp_label.setText(f"Temperature: {self.temp_slider.value()}")
        self.tint_label.setText(f"Tint: {self.tint_slider.value()}")
        self.preview_timer.start(30)

    def calculate_ratios(self, use_selection=True):
        """Logic for both Auto and Selection Area using Mutterer math"""
        target_x, target_y, target_w, target_h = self.x, self.y, self.w, self.h
        
        if use_selection:
            sel = self.doc.selection()
            if not sel or sel.width() < 1 or sel.height() < 1:
                QMessageBox.warning(self, "Error", "No selection found!\nUse a selection tool to highlight a gray area first.")
                return
            target_x, target_y, target_w, target_h = sel.x(), sel.y(), sel.width(), sel.height()

        # Grab pixel data from the chosen area
        data = self.node.pixelData(target_x, target_y, target_w, target_h)
        pixels = bytearray(data)
        
        t_r = t_g = t_b = count = 0
        # Optimization: Sample step to prevent lag on huge selections
        step = 4 * max(1, int((target_w * target_h) / 50000)) 
        
        for i in range(0, len(pixels), step):
            t_b += pixels[i]
            t_g += pixels[i+1]
            t_r += pixels[i+2]
            count += 1
            
        if count == 0: return
        
        avg_r, avg_g, avg_b = t_r/count, t_g/count, t_b/count
        gray_target = (avg_r + avg_g + avg_b) / 3.0
        
        # Calculate Ratios
        self.base_r = gray_target / max(avg_r, 1)
        self.base_g = gray_target / max(avg_g, 1)
        self.base_b = gray_target / max(avg_b, 1)
        
        self.apply_transformation()

    def apply_transformation(self):
        # 1. Strength Blending
        s = self.strength_slider.value() / 100.0
        m_r = 1.0 + (self.base_r - 1.0) * s
        m_g = 1.0 + (self.base_g - 1.0) * s
        m_b = 1.0 + (self.base_b - 1.0) * s
        
        # 2. Manual Supplement
        t_off = self.temp_slider.value() / 200.0
        tint_off = self.tint_slider.value() / 200.0
        
        final_r = m_r * (1.0 + t_off)
        final_g = m_g * (1.0 + tint_off)
        final_b = m_b * (1.0 - t_off)
        
        # 3. Process image data
        pixels = bytearray(self.original_data)
        for i in range(0, len(pixels), 4):
            pixels[i]   = max(0, min(255, int(pixels[i] * final_b)))
            pixels[i+1] = max(0, min(255, int(pixels[i+1] * final_g)))
            pixels[i+2] = max(0, min(255, int(pixels[i+2] * final_r)))
            
        self.current_preview = QByteArray(pixels)
        self.node.setPixelData(self.current_preview, self.x, self.y, self.w, self.h)
        self.doc.refreshProjection()

    def eventFilter(self, obj, event):
        if obj == self.comp_btn:
            if event.type() == QEvent.Enter:
                self.node.setPixelData(self.original_data, self.x, self.y, self.w, self.h)
                self.doc.refreshProjection()
            elif event.type() == QEvent.Leave:
                self.node.setPixelData(self.current_preview, self.x, self.y, self.w, self.h)
                self.doc.refreshProjection()
        return super().eventFilter(obj, event)

    def reset_all(self):
        self.base_r = self.base_g = self.base_b = 1.0
        self.strength_slider.setValue(100)
        self.temp_slider.setValue(0)
        self.tint_slider.setValue(0)
        self.apply_transformation()

    def cancel(self):
        self.node.setPixelData(self.original_data, self.x, self.y, self.w, self.h)
        self.doc.refreshProjection()
        self.reject()

# Run
if Krita.instance().activeDocument():
    dlg = WhiteBalanceDialog()
    dlg.exec_()