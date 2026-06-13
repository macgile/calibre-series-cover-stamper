from qt.core import (
    QCheckBox,
    QComboBox,
    QWidget,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
)

from calibre_plugins.annotate_series_cover.i18n import LANGUAGES, normalize_language, tr
from calibre_plugins.annotate_series_cover.prefs import current_prefs, save_prefs, DEFAULTS


class ConfigWidget(QWidget):
    """Build the Calibre-hosted preferences form for badge stamping."""

    def __init__(self, parent=None):
        """Create the settings UI."""
        super().__init__(parent)
        self.setMinimumWidth(520)

        self._orig = current_prefs()
        self.lang = normalize_language(self._orig.get('language', DEFAULTS.get('language', 'en')))

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.language = QComboBox()
        for code, label in LANGUAGES:
            self.language.addItem(label, code)
        idx = self.language.findData(self.lang)
        if idx >= 0:
            self.language.setCurrentIndex(idx)
        form.addRow(tr(self.lang, 'config_language'), self.language)

        note = QLabel(tr(self.lang, 'config_badge_note'))
        note.setWordWrap(True)
        note.setStyleSheet('color: gray; font-size: 10px;')
        form.addRow('', note)

        self.badge_size = QSpinBox()
        self.badge_size.setRange(0, 5000)
        self.badge_size.setValue(int(self._orig.get('badge_size', 0)))
        self.badge_size.setSuffix(tr(self.lang, 'suffix_px_auto'))
        form.addRow(tr(self.lang, 'config_badge_size'), self.badge_size)

        self.auto_badge_percent = QDoubleSpinBox()
        self.auto_badge_percent.setRange(4.0, 40.0)
        self.auto_badge_percent.setDecimals(1)
        self.auto_badge_percent.setSingleStep(0.5)
        self.auto_badge_percent.setValue(float(self._orig.get('auto_badge_percent', 16.0)))
        self.auto_badge_percent.setSuffix(tr(self.lang, 'suffix_percent_small_side'))
        form.addRow(tr(self.lang, 'config_auto_badge_size'), self.auto_badge_percent)

        self.position = QComboBox()
        positions = [
            ('bottom_right', tr(self.lang, 'pos_bottom_right')),
            ('bottom_left', tr(self.lang, 'pos_bottom_left')),
            ('top_right', tr(self.lang, 'pos_top_right')),
            ('top_left', tr(self.lang, 'pos_top_left')),
            ('bottom_center', tr(self.lang, 'pos_bottom_center')),
            ('top_center', tr(self.lang, 'pos_top_center')),
            ('center', tr(self.lang, 'pos_center')),
        ]
        for val, label in positions:
            self.position.addItem(label, val)
        idx = self.position.findData(self._orig.get('position', 'bottom_right'))
        if idx >= 0:
            self.position.setCurrentIndex(idx)
        form.addRow(tr(self.lang, 'config_position'), self.position)

        self.margin = QSpinBox()
        self.margin.setRange(0, 1000)
        self.margin.setValue(int(self._orig.get('margin', 24)))
        self.margin.setSuffix(tr(self.lang, 'suffix_px'))
        form.addRow(tr(self.lang, 'config_margin'), self.margin)

        self.shadow_enabled = QCheckBox(tr(self.lang, 'config_shadow_enabled'))
        self.shadow_enabled.setChecked(bool(self._orig.get('shadow_enabled', True)))
        form.addRow(tr(self.lang, 'config_shadow'), self.shadow_enabled)

        self.output_format = QComboBox()
        formats = [
            ('original', tr(self.lang, 'format_original')),
            ('jpeg', tr(self.lang, 'format_jpeg')),
            ('png', tr(self.lang, 'format_png')),
        ]
        for val, label in formats:
            self.output_format.addItem(label, val)
        idx = self.output_format.findData(self._orig.get('output_format', 'original'))
        if idx >= 0:
            self.output_format.setCurrentIndex(idx)
        form.addRow(tr(self.lang, 'config_output_format'), self.output_format)

        layout.addLayout(form)

    def save_settings(self):
        """Collect form values and persist plugin preferences."""
        values = {
            'language': self.language.currentData() or DEFAULTS.get('language', 'en'),
            'badge_size': self.badge_size.value(),
            'auto_badge_percent': self.auto_badge_percent.value(),
            'position': self.position.currentData(),
            'margin': self.margin.value(),
            'shadow_enabled': self.shadow_enabled.isChecked(),
            'output_format': self.output_format.currentData(),
        }
        save_prefs(values)
