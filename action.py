import glob
import math
import os
import traceback

from qt.core import (
    Qt,
    QRect,
    QRectF,
    QImage,
    QPainter,
    QFont,
    QFontMetrics,
    QColor,
    QPen,
    QDialog,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QTableWidget,
    QTableWidgetItem,
    QDialogButtonBox,
    QIcon,
    QPainterPath,
    QPixmap,
    QPointF,
    QRadialGradient,
)
from calibre.constants import config_dir
from calibre.utils.img import image_from_data, image_to_data

from calibre.gui2 import QApplication, error_dialog, info_dialog
from calibre.gui2.actions import InterfaceAction

try:
    from calibre.gui2.actions import get_icons
except Exception:
    try:
        from calibre.gui2 import get_icons
    except Exception:
        get_icons = None
from calibre_plugins.annotate_series_cover.prefs import current_prefs, DEFAULTS
from calibre_plugins.annotate_series_cover.i18n import normalize_language, tr


# Prefix used for one-time original cover backups stored in each book folder.
BACKUP_PREFIX = '_cover_backup'


class CoverBatchDialog(QDialog):
    """Single dialog used to review, annotate and restore selected book covers."""

    # Translation keys for the table columns shown in the batch dialog.
    COLUMN_KEYS = ('col_id', 'col_title', 'col_series', 'col_volume', 'col_backup', 'col_status')

    def __init__(self, parent, entries, annotatable_count, lang='en'):
        """Build the batch dialog UI and initialize row state."""
        super().__init__(parent)
        self.lang = normalize_language(lang)
        self.entries = entries
        self.rows_by_id = {}
        self._processing = False

        self.setWindowTitle(tr(self.lang, 'dialog_title'))
        self.setMinimumWidth(850)
        self.setMinimumHeight(420)

        layout = QVBoxLayout(self)

        selected_count = len(entries)
        ignored_count = max(0, selected_count - annotatable_count)
        self.selected_count = selected_count
        self.annotatable_count = annotatable_count
        self.ignored_count = ignored_count
        self.summary_label = QLabel(
            tr(self.lang, 'summary', selected=selected_count, annotatable=annotatable_count, ignored=ignored_count)
        )
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        self.table = QTableWidget(len(entries), len(self.COLUMN_KEYS), self)
        self.table.setHorizontalHeaderLabels([tr(self.lang, key) for key in self.COLUMN_KEYS])
        self.table.setSelectionBehavior(self.select_rows_mode())
        self.table.setSelectionMode(self.single_selection_mode())
        self.populate_table(entries)
        layout.addWidget(self.table)

        self.status_label = QLabel(tr(self.lang, 'ready'))
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.progress = QProgressBar(self)
        self.progress.setRange(0, max(1, selected_count))
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        buttons = QHBoxLayout()
        self.options_button = QPushButton(tr(self.lang, 'options_button'))
        buttons.addWidget(self.options_button)
        buttons.addStretch(1)
        self.annotate_button = QPushButton(tr(self.lang, 'annotate_button'))
        self.restore_button = QPushButton(tr(self.lang, 'restore_button'))
        self.close_button = QPushButton(tr(self.lang, 'close_button'))

        try:
            self.options_button.setAutoDefault(False)
            self.annotate_button.setAutoDefault(False)
            self.restore_button.setAutoDefault(False)
            self.close_button.setAutoDefault(False)
            self.options_button.setDefault(False)
            self.annotate_button.setDefault(False)
            self.restore_button.setDefault(False)
            self.close_button.setDefault(False)
        except Exception:
            pass

        self.annotate_button.setEnabled(annotatable_count > 0)
        self.close_button.clicked.connect(self.accept)

        buttons.addWidget(self.annotate_button)
        buttons.addWidget(self.restore_button)
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)

        try:
            self.table.resizeColumnsToContents()
            self.table.horizontalHeader().setStretchLastSection(True)
        except Exception:
            pass

    def select_rows_mode(self):
        """Return the Qt flag used for row selection."""
        try:
            from qt.core import QAbstractItemView
            return getattr(getattr(QAbstractItemView, 'SelectionBehavior', QAbstractItemView), 'SelectRows')
        except Exception:
            return 1

    def single_selection_mode(self):
        """Return the Qt flag used for single-row selection."""
        try:
            from qt.core import QAbstractItemView
            return getattr(getattr(QAbstractItemView, 'SelectionMode', QAbstractItemView), 'SingleSelection')
        except Exception:
            return 1

    def apply_language(self, lang):
        """Refresh visible dialog text after a language change."""
        self.lang = normalize_language(lang)
        self.setWindowTitle(tr(self.lang, 'dialog_title'))
        self.summary_label.setText(
            tr(self.lang, 'summary', selected=self.selected_count, annotatable=self.annotatable_count, ignored=self.ignored_count)
        )
        self.table.setHorizontalHeaderLabels([tr(self.lang, key) for key in self.COLUMN_KEYS])
        self.options_button.setText(tr(self.lang, 'options_button'))
        self.annotate_button.setText(tr(self.lang, 'annotate_button'))
        self.restore_button.setText(tr(self.lang, 'restore_button'))
        self.close_button.setText(tr(self.lang, 'close_button'))
        for entry in self.entries:
            self.update_backup(entry['book_id'], bool(entry.get('backup_exists')))
            self.update_status_from_entry(entry['book_id'])

    def entry_status_text(self, entry):
        """Resolve a stored status key into localized text."""
        key = entry.get('status_key')
        kwargs = entry.get('status_kwargs') or {}
        if key:
            return tr(self.lang, key, **kwargs)
        return entry.get('status') or ''

    def update_status_from_entry(self, book_id):
        """Refresh one table status from its entry data."""
        row = self.rows_by_id.get(book_id)
        if row is None:
            return
        entry = None
        for candidate in self.entries:
            if candidate.get('book_id') == book_id:
                entry = candidate
                break
        if entry is None:
            return
        item = self.table.item(row, 5)
        if item is None:
            item = QTableWidgetItem('')
            self.table.setItem(row, 5, item)
        item.setText(self.entry_status_text(entry))

    def populate_table(self, entries):
        """Fill the table with selected book information."""
        for row, entry in enumerate(entries):
            self.rows_by_id[entry['book_id']] = row
            values = [
                str(entry['book_id']),
                entry.get('title') or '',
                entry.get('series') or '',
                entry.get('series_index_text') or '',
                tr(self.lang, 'yes') if entry.get('backup_exists') else tr(self.lang, 'no'),
                self.entry_status_text(entry),
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                try:
                    item.setFlags(item.flags() & ~self.item_editable_flag())
                except Exception:
                    pass
                self.table.setItem(row, col, item)

    def item_editable_flag(self):
        """Return the Qt flag used to disable item editing."""
        return getattr(getattr(Qt, 'ItemFlag', Qt), 'ItemIsEditable')

    def set_processing(self, processing, message=None):
        """Enable or disable controls while a task is running."""
        self._processing = bool(processing)
        self.options_button.setEnabled(not processing)
        self.annotate_button.setEnabled(not processing and any(e.get('annotatable') for e in self.entries))
        self.restore_button.setEnabled(not processing)
        self.close_button.setEnabled(not processing)
        if message:
            self.status_label.setText(message)
        QApplication.processEvents()

    def closeEvent(self, event):
        """Prevent closing the dialog during active processing."""
        if self._processing:
            self.status_label.setText(tr(self.lang, 'processing_close_disabled'))
            try:
                event.ignore()
                return
            except Exception:
                pass
        try:
            event.accept()
        except Exception:
            pass

    def update_status_key(self, book_id, key, **kwargs):
        """Store and display a localized status for one book."""
        row = self.rows_by_id.get(book_id)
        if row is None:
            return
        for entry in self.entries:
            if entry.get('book_id') == book_id:
                entry['status_key'] = key
                entry['status_kwargs'] = kwargs
                entry.pop('status', None)
                break
        item = self.table.item(row, 5)
        if item is None:
            item = QTableWidgetItem('')
            self.table.setItem(row, 5, item)
        item.setText(tr(self.lang, key, **kwargs))
        QApplication.processEvents()

    def update_backup(self, book_id, exists):
        """Update the backup availability cell for one book."""
        row = self.rows_by_id.get(book_id)
        if row is None:
            return
        item = self.table.item(row, 4)
        if item is None:
            item = QTableWidgetItem('')
            self.table.setItem(row, 4, item)
        item.setText(tr(self.lang, 'yes') if exists else tr(self.lang, 'no'))
        QApplication.processEvents()

    def set_progress(self, value, maximum=None, text=None):
        """Update the progress bar and optional status text."""
        if maximum is not None:
            self.progress.setRange(0, max(1, int(maximum)))
        self.progress.setValue(int(value))
        if text is not None:
            self.status_label.setText(str(text))
        QApplication.processEvents()


class SeriesCoverStamperAction(InterfaceAction):
    # Internal action name used by Calibre toolbar/action storage.
    name = 'Series Cover Stamper'
    action_spec = (
        'Series Cover Stamper',
        'images/icon.png',
        'Stamp series number on selected book covers',
        None,
    )
    action_type = 'current'
    dont_add_to = ()

    def genesis(self):
        """Connect the Calibre action, icon and localized action label."""
        self.apply_action_icon()
        self.refresh_action_label()
        self.qaction.triggered.connect(self.do_annotate)

    def initialization_complete(self):
        """Re-apply visible action attributes after Calibre finishes initialization."""
        self.apply_action_icon()
        self.refresh_action_label()

    def build_plugin_icon(self):
        """Load the icon from bundled plugin resources with safe fallbacks."""
        resource_names = ('images/icon.png', 'icon.png')

        # Preferred path for third-party plugin resources stored inside the ZIP.
        for owner_name in ('interface_action_base_plugin', 'base_plugin', 'plugin'):
            owner = getattr(self, owner_name, None)
            loader = getattr(owner, 'load_resources', None)
            if loader is None:
                continue
            try:
                resources = loader(resource_names)
            except Exception:
                resources = {}
            for name in resource_names:
                raw = resources.get(name) if isinstance(resources, dict) else None
                if not raw:
                    continue
                pixmap = QPixmap()
                if pixmap.loadFromData(raw):
                    return QIcon(pixmap)

        # Fallback for Calibre resource lookup when available.
        if get_icons is not None:
            for name in resource_names:
                try:
                    icon = get_icons(name)
                    if icon is not None and not icon.isNull():
                        return icon
                except Exception:
                    pass

        return QIcon()

    def apply_action_icon(self):
        """Apply the plugin icon to the Calibre toolbar/menu action."""
        try:
            icon = self.build_plugin_icon()
            if icon is not None and not icon.isNull():
                self.qaction.setIcon(icon)
        except Exception:
            pass

    def refresh_action_label(self):
        """Refresh the toolbar/menu action text from the selected language."""
        try:
            lang = normalize_language(self.current_preferences().get('language'))
            self.qaction.setText(tr(lang, 'plugin_name'))
            self.qaction.setToolTip(tr(lang, 'action_tooltip'))
            self.qaction.setStatusTip(tr(lang, 'action_tooltip'))
            self.apply_action_icon()
        except Exception:
            pass

    def do_annotate(self):
        """Run the plugin action with top-level error handling."""
        try:
            self._do_annotate()
        except Exception as e:
            log_path = self.log_path()
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write(f'FATAL: {e}\n')
                f.write(traceback.format_exc())
            lang = normalize_language(self.current_preferences().get('language'))
            error_dialog(self.gui, tr(lang, 'plugin_name'), tr(lang, 'fatal_error', error=e, log_path=log_path))

    def log_path(self):
        """Return the temporary log file path used by this plugin."""
        return os.path.join(os.environ.get('TEMP') or os.environ.get('TMP') or config_dir, 'series_cover_stamper.log')

    def _do_annotate(self):
        """Collect selected books and open the batch dialog."""
        log_path = self.log_path()
        with open(log_path, 'w', encoding='utf-8') as f:
            f.write('=== ANNOTATE START ===\n')

        def log(msg):
            """Append one message to the current plugin log file."""
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write(str(msg) + '\n')

        db = self.database_api()
        rows = self.selected_book_ids()
        p = self.current_preferences()
        lang = normalize_language(p.get('language'))
        log(f'selected ids: {sorted(rows)}')

        if not rows:
            log('no selected books - stop')
            info_dialog(
                self.gui,
                tr(lang, 'plugin_name'),
                tr(lang, 'no_selected_books'),
            )
            log('=== ANNOTATE END ===')
            return

        log(f'preferences: language={lang!r}, text_format={p.get("text_format")!r}, font_size={p.get("font_size")}, auto_font_percent={p.get("auto_font_percent")}, position={p.get("position")!r}')

        entries = []
        annotatable_count = 0
        for book_id in rows:
            try:
                mi = self.get_metadata_for_book(db, book_id)
                series_index_text = self.format_series_index(mi.series_index) if mi.series_index is not None else ''
                annotatable = bool(mi.series) and mi.series_index is not None and mi.series_index > 0
                if annotatable:
                    annotatable_count += 1
                    status_key = 'ready_to_annotate'
                else:
                    status_key = 'ignored_no_series'
                backup_path = self.find_cover_backup(db, book_id, mi)
                entry = {
                    'book_id': book_id,
                    'title': mi.title or tr(lang, 'book_fallback', book_id=book_id),
                    'series': mi.series or '',
                    'series_index': mi.series_index,
                    'series_index_text': series_index_text,
                    'annotatable': annotatable,
                    'status_key': status_key,
                    'backup_exists': bool(backup_path),
                    'metadata': mi,
                }
                log(f'book {book_id}: {entry["title"]!r} | series={mi.series!r} idx={mi.series_index} backup={bool(backup_path)} -> {status_key}')
            except Exception as exc:
                entry = {
                    'book_id': book_id,
                    'title': tr(lang, 'book_fallback', book_id=book_id),
                    'series': '',
                    'series_index': None,
                    'series_index_text': '',
                    'annotatable': False,
                    'status_key': 'invalid_id_status',
                    'status_kwargs': {'error': exc},
                    'backup_exists': False,
                    'metadata': None,
                }
                log(f'book {book_id}: invalid id: {exc}')
            entries.append(entry)

        dialog = CoverBatchDialog(self.gui, entries, annotatable_count, lang)
        dialog.options_button.clicked.connect(lambda: self.open_options_from_dialog(dialog, log))
        dialog.annotate_button.clicked.connect(lambda: self.run_annotation(db, dialog, entries, log, log_path))
        dialog.restore_button.clicked.connect(lambda: self.run_restore(db, dialog, entries, log, log_path))
        self.exec_dialog(dialog)
        log('=== ANNOTATE END ===')

    def open_options_from_dialog(self, dialog, log):
        """Open the plugin configuration from the batch dialog.

        Calibre normally hosts ConfigWidget and calls save_settings() when the
        user validates its own OK/Apply buttons.  This method reuses that
        mechanism when available, then reloads preferences so the next
        annotation run uses the freshly saved options.
        """
        log('options: open requested')
        try:
            base_plugin = getattr(self, 'interface_action_base_plugin', None)
            if base_plugin is not None and hasattr(base_plugin, 'do_user_config'):
                try:
                    base_plugin.do_user_config(dialog)
                except TypeError:
                    try:
                        base_plugin.do_user_config(parent=dialog)
                    except TypeError:
                        base_plugin.do_user_config()
            else:
                self.open_options_fallback(dialog)

            p = self.current_preferences()
            lang = normalize_language(p.get('language'))
            self.refresh_action_label()
            dialog.apply_language(lang)
            dialog.status_label.setText(tr(lang, 'options_reloaded'))
            log(
                'options: reloaded '
                f'text_format={p.get("text_format")!r}, '
                f'font_size={p.get("font_size")}, '
                f'auto_font_percent={p.get("auto_font_percent")}, '
                f'position={p.get("position")!r}'
            )
        except Exception as exc:
            log(f'options: failed: {exc}')
            log(traceback.format_exc())
            lang = normalize_language(self.current_preferences().get('language'))
            error_dialog(self.gui, tr(lang, 'plugin_name'), tr(lang, 'options_open_failed', error=exc))

    def open_options_fallback(self, parent):
        """Fallback configuration dialog for Calibre builds without do_user_config()."""
        from calibre_plugins.annotate_series_cover.config_widget import ConfigWidget

        dlg = QDialog(parent)
        lang = normalize_language(self.current_preferences().get('language'))
        dlg.setWindowTitle(tr(lang, 'options_window_title'))
        layout = QVBoxLayout(dlg)
        widget = ConfigWidget(dlg)
        layout.addWidget(widget)

        buttons = QDialogButtonBox(
            getattr(getattr(QDialogButtonBox, 'StandardButton', QDialogButtonBox), 'Ok')
            | getattr(getattr(QDialogButtonBox, 'StandardButton', QDialogButtonBox), 'Cancel')
        )
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)

        if self.exec_dialog(dlg):
            widget.save_settings()

    def run_annotation(self, db, dialog, entries, log, log_path):
        """Annotate every selected book that has valid series metadata."""
        p = self.current_preferences()
        lang = normalize_language(p.get('language'))
        dialog.apply_language(lang)
        annotatable = [e for e in entries if e.get('annotatable')]
        total = len(annotatable)
        processed = 0
        errors = 0
        skipped_no_cover = 0
        backup_errors = 0
        refreshed_ids = []

        if not annotatable:
            info_dialog(self.gui, tr(lang, 'plugin_name'), tr(lang, 'no_annotatable_books'))
            return

        log('=== ANNOTATION RUN START ===')
        dialog.set_processing(True, tr(lang, 'annotation_running'))
        dialog.set_progress(0, total, tr(lang, 'annotation_running'))

        for index, entry in enumerate(annotatable, 1):
            book_id = entry['book_id']
            title = entry.get('title') or tr(lang, 'book_fallback', book_id=book_id)
            dialog.set_progress(index - 1, total, tr(lang, 'annotation_item', index=index, total=total, title=title))
            dialog.update_status_key(book_id, 'status_annotation_running')
            QApplication.processEvents()

            try:
                mi = self.get_metadata_for_book(db, book_id)
                series = mi.series
                series_index = mi.series_index
                if not series or series_index is None or series_index <= 0:
                    dialog.update_status_key(book_id, 'status_skip_invalid')
                    log(f'book {book_id}: skip during run, invalid series/index')
                    continue

                number_text = self.format_series_index(series_index)
                log(f'book {book_id}: badge_number={number_text!r}')

                cover_bytes = self.get_cover_bytes(db, book_id)
                if not cover_bytes:
                    skipped_no_cover += 1
                    dialog.update_status_key(book_id, 'status_no_cover')
                    log(f'book {book_id}: skip no cover')
                    continue

                try:
                    backup_path, created = self.backup_original_cover(db, book_id, mi, cover_bytes)
                    entry['backup_exists'] = True
                    dialog.update_backup(book_id, True)
                    if created:
                        dialog.update_status_key(book_id, 'status_backup_created')
                    else:
                        dialog.update_status_key(book_id, 'status_backup_kept')
                    log(f'book {book_id}: backup={backup_path} created={created}')
                except Exception as backup_exc:
                    backup_errors += 1
                    errors += 1
                    dialog.update_status_key(book_id, 'status_backup_error', error=backup_exc)
                    log(f'book {book_id}: backup failed: {backup_exc}')
                    log(traceback.format_exc())
                    continue

                annotated, annotation_info = self.annotate_image(cover_bytes, number_text, p)
                if annotated is None:
                    errors += 1
                    dialog.update_status_key(book_id, 'status_annotation_error')
                    log(f'book {book_id}: annotate_image returned None')
                    continue
                log(f'book {book_id}: annotation={annotation_info}')

                output_format = self.resolve_output_format(cover_bytes, p.get('output_format', 'original'))
                annotated_bytes = image_to_data(annotated, fmt=output_format)
                if not annotated_bytes:
                    errors += 1
                    dialog.update_status_key(book_id, 'status_encoding_empty')
                    log(f'book {book_id}: empty encoded image')
                    continue

                self.set_cover_bytes(db, book_id, annotated_bytes)
                refreshed_ids.append(book_id)
                processed += 1
                dialog.update_status_key(book_id, 'status_annotated')
                log(f'book {book_id}: SUCCESS')
            except Exception as exc:
                errors += 1
                dialog.update_status_key(book_id, 'status_exception', error=exc)
                log(f'book {book_id}: EXCEPTION {exc}')
                log(traceback.format_exc())

            dialog.set_progress(index, total, tr(lang, 'annotation_item_done', index=index, total=total))

        if refreshed_ids:
            self.refresh_library_view(list(dict.fromkeys(refreshed_ids)), log)

        summary = tr(
            lang,
            'annotation_summary',
            processed=processed,
            skipped_no_cover=skipped_no_cover,
            backup_errors=backup_errors,
            errors=errors,
            log_path=log_path,
        )
        dialog.set_progress(total, total, summary.replace('\n\n', '\n'))
        dialog.set_processing(False, tr(lang, 'annotation_done'))
        if errors:
            error_dialog(self.gui, tr(lang, 'plugin_name'), summary)
        else:
            info_dialog(self.gui, tr(lang, 'plugin_name'), summary)
        log('=== ANNOTATION RUN END ===')

    def run_restore(self, db, dialog, entries, log, log_path):
        """Restore selected covers from existing backup files.

        Uses the same set_cover_bytes() method as run_annotation() to ensure
        consistent and reliable cover writing.
        """
        lang = normalize_language(self.current_preferences().get('language'))
        dialog.apply_language(lang)
        log('=== RESTORE RUN START ===')
        restore_items = []
        for entry in entries:
            book_id = entry['book_id']
            # Use the same find_cover_backup() that the annotation dialog uses.
            try:
                mi = self.get_metadata_for_book(db, book_id)
            except Exception as exc:
                log(f'restore: book {book_id} metadata error: {exc}')
                continue
            backup_path = self.find_cover_backup(db, book_id, mi)
            log(f'restore: book {book_id} backup_path={backup_path!r}')
            if backup_path:
                restore_items.append((entry, mi, backup_path))

        if not restore_items:
            log('restore: no backup found')
            info_dialog(self.gui, tr(lang, 'plugin_name'), tr(lang, 'no_backup_found'))
            return

        total = len(restore_items)
        restored = 0
        errors = 0
        refreshed_ids = []
        dialog.set_processing(True, tr(lang, 'restore_running'))
        dialog.set_progress(0, total, tr(lang, 'restore_running'))

        for index, (entry, mi, backup_path) in enumerate(restore_items, 1):
            book_id = entry['book_id']
            title = entry.get('title') or getattr(mi, 'title', None) or tr(lang, 'book_fallback', book_id=book_id)
            dialog.set_progress(index - 1, total, tr(lang, 'restore_item', index=index, total=total, title=title))
            dialog.update_status_key(book_id, 'status_restore_running')
            QApplication.processEvents()
            try:
                with open(backup_path, 'rb') as f:
                    cover_bytes = f.read()
                if not cover_bytes:
                    raise ValueError(tr(lang, 'backup_empty_file'))

                # Use the SAME set_cover_bytes() as run_annotation().
                success = self.set_cover_bytes(db, book_id, cover_bytes)
                if not success:
                    raise RuntimeError('set_cover_bytes returned False')
                log(f'restore: book {book_id} set_cover_bytes OK')

                refreshed_ids.append(book_id)
                restored += 1
                entry['backup_exists'] = True
                dialog.update_backup(book_id, True)
                dialog.update_status_key(book_id, 'status_restored')
                log(f'restore: book {book_id} SUCCESS from {backup_path}')
            except Exception as exc:
                errors += 1
                dialog.update_status_key(book_id, 'status_restore_error', error=exc)
                log(f'restore: book {book_id} failed: {exc}')
                log(traceback.format_exc())
            dialog.set_progress(index, total, tr(lang, 'restore_item_done', index=index, total=total))

        if refreshed_ids:
            self.refresh_library_view(list(dict.fromkeys(refreshed_ids)), log)

        summary = tr(
            lang,
            'restore_summary',
            restored=restored,
            errors=errors,
            log_path=log_path,
        )
        dialog.set_progress(total, total, summary.replace('\n\n', '\n'))
        dialog.set_processing(False, tr(lang, 'restore_done'))
        if errors:
            error_dialog(self.gui, tr(lang, 'plugin_name'), summary)
        else:
            info_dialog(self.gui, tr(lang, 'plugin_name'), summary)
        log('=== RESTORE RUN END ===')

    def selected_book_ids(self):
        """Return unique Calibre IDs from the current selection only."""
        ids = []
        view = getattr(self.gui, 'library_view', None)
        if view is None:
            return ids

        try:
            ids = list(view.get_selected_ids() or [])
        except Exception:
            ids = []

        if ids:
            return list(dict.fromkeys(ids))

        # Fallback strict : use the current selection model only, never all displayed books.
        try:
            model = view.model()
            selection_model = view.selectionModel()
            if selection_model is not None:
                for index in selection_model.selectedRows():
                    try:
                        book_id = model.id(index.row())
                        if book_id is not None:
                            ids.append(book_id)
                    except Exception:
                        continue
        except Exception:
            pass

        return list(dict.fromkeys(ids))

    def current_preferences(self):
        """Read plugin preferences with defaults applied."""
        return current_prefs()

    def database_api(self):
        """Return the modern Calibre database API when available."""
        current_db = self.gui.current_db
        return getattr(current_db, 'new_api', current_db)

    def get_metadata_for_book(self, db, book_id):
        """Read metadata for a Calibre book ID."""
        if hasattr(db, 'has_id') and not db.has_id(book_id):
            raise KeyError(f'book id {book_id} is not present in the current database')
        try:
            return db.get_metadata(book_id)
        except TypeError:
            return db.get_metadata(book_id, index_is_id=True)

    def get_cover_bytes(self, db, book_id):
        """Read cover image bytes for a Calibre book ID."""
        try:
            return db.cover(book_id)
        except TypeError:
            return db.cover(book_id, index_is_id=True)

    def set_cover_bytes(self, db, book_id, cover_bytes):
        """Write cover image bytes for a Calibre book ID.

        Returns True on success, False on failure.
        """
        # Calibre modern API: db.set_cover(book_id, cover_bytes)
        try:
            db.set_cover(book_id, cover_bytes)
            return True
        except TypeError:
            pass
        except Exception:
            pass

        # Calibre >= 6 batch API: db.set_cover({book_id: cover_bytes})
        try:
            db.set_cover({book_id: cover_bytes})
            return True
        except Exception:
            pass

        return False

    def refresh_library_view(self, book_ids, log):
        """Refresh Calibre rows after cover changes while preserving active filters."""
        # Try the most specific refresh first: only the changed books.
        model = self.gui.library_view.model()

        # 1) refresh_ids() – preserves the current search/filter.
        try:
            model.refresh_ids(book_ids)
            return
        except AttributeError:
            pass
        except Exception as exc:
            log(f'  refresh_ids() failed: {exc}')

        # 2) refresh(book_ids) – may preserve filters on some Calibre versions.
        try:
            model.refresh(book_ids)
            return
        except TypeError:
            pass
        except Exception as exc:
            log(f'  refresh(book_ids) failed: {exc}')

        # 3) Trigger a lightweight cover update via the database API.
        #    This avoids model.refresh() (no args) which would reset the view filter.
        try:
            db = self.gui.current_db
            if db is not None:
                api = getattr(db, 'new_api', db)
                if hasattr(api, 'refresh_books'):
                    api.refresh_books(book_ids)
                    return
        except Exception as exc:
            log(f'  db.refresh_books() failed: {exc}')

        # 4) Last resort: patch selected rows individually to update covers
        #    without resetting the whole view.
        try:
            from qt.core import QModelIndex
            for book_id in book_ids:
                row = model.id_to_row(book_id)
                if row is not None:
                    idx = model.index(row, 0, QModelIndex())
                    model.dataChanged.emit(idx, idx)
            return
        except Exception as exc:
            log(f'  cover patch failed: {exc}')

        log('  WARNING: no suitable refresh method found — covers may not update immediately.')

    def backup_original_cover(self, db, book_id, mi, cover_bytes):
        """Create the original cover backup once, and only once.

        The backup is stored in the Calibre book folder.  If any local backup
        made by this plugin already exists for the book, it is returned and is
        never overwritten.  This preserves the true original cover even if the
        user runs the annotation several times with different settings.
        """
        existing = self.find_cover_backup(db, book_id, mi, include_legacy=False)
        if existing:
            return existing, False

        book_dir = self.book_folder_path(db, book_id, mi)
        if not book_dir:
            raise RuntimeError(tr(normalize_language(self.current_preferences().get('language')), 'backup_folder_missing'))
        if not os.path.isdir(book_dir):
            raise RuntimeError(tr(normalize_language(self.current_preferences().get('language')), 'backup_folder_missing_path', path=book_dir))

        ext = self.detect_image_extension(cover_bytes)
        backup_path = os.path.join(book_dir, f'{BACKUP_PREFIX}.{ext}')

        # Final safety check: do not overwrite a backup even if it appeared
        # between find_cover_backup() and the write operation.
        if os.path.exists(backup_path):
            return backup_path, False

        with open(backup_path, 'xb') as f:
            f.write(cover_bytes)
        return backup_path, True

    def find_cover_backup(self, db, book_id, mi=None, include_legacy=True):
        """Find the original cover backup for one book."""
        book_dir = self.book_folder_path(db, book_id, mi)
        if book_dir and os.path.isdir(book_dir):
            # Check exact filenames (avoids glob() issues with brackets in paths).
            for name in (f'{BACKUP_PREFIX}.jpg', f'{BACKUP_PREFIX}.jpeg', f'{BACKUP_PREFIX}.png',
                         f'{BACKUP_PREFIX}.webp',
                         'cover.original.annotate_series_cover.jpg',
                         'cover.original.annotate_series_cover.jpeg',
                         'cover.original.annotate_series_cover.png',
                         'cover.original.annotate_series_cover.webp'):
                path = os.path.join(book_dir, name)
                if os.path.isfile(path):
                    return path

        if not include_legacy:
            return None

        # Compatibility with v1.1.1-v1.1.4, which stored backups in calibre's config dir.
        legacy_root = os.path.join(config_dir, 'plugins', 'annotate_series_cover_backups')
        legacy_candidates = []
        for ext in ('jpg', 'jpeg', 'png', 'webp'):
            legacy_candidates.extend(glob.glob(os.path.join(legacy_root, '**', f'{book_id}_*.{ext}'), recursive=True))
        legacy_candidates = [p for p in legacy_candidates if os.path.isfile(p)]
        if legacy_candidates:
            return sorted(legacy_candidates, key=lambda p: (os.path.getmtime(p), p))[0]
        return None

    def book_folder_path(self, db, book_id, mi=None):
        """Resolve the filesystem folder for a Calibre book."""
        # Direct API attempts.
        for target in (db, getattr(self.gui, 'current_db', None)):
            if target is None:
                continue
            for method_name in ('abspath',):
                method = getattr(target, method_name, None)
                if method is None:
                    continue
                for args, kwargs in (((book_id,), {}), ((book_id,), {'index_is_id': True})):
                    try:
                        path = method(*args, **kwargs)
                        if path and isinstance(path, str):
                            return path if os.path.isdir(path) else os.path.dirname(path)
                    except Exception:
                        pass

            method = getattr(target, 'cover_abspath', None)
            if method is not None:
                for args, kwargs in (((book_id,), {}), ((book_id,), {'index_is_id': True})):
                    try:
                        cover_path = method(*args, **kwargs)
                        if cover_path and isinstance(cover_path, str):
                            return os.path.dirname(cover_path)
                    except Exception:
                        pass

        # Modern Cache API: path is the relative book folder inside the library.
        relpath = None
        try:
            relpath = db.field_for('path', book_id)
        except Exception:
            pass
        if not relpath and mi is not None:
            try:
                relpath = getattr(mi, 'path', None)
            except Exception:
                pass

        library_path = self.library_path_for_backup(db)
        if library_path and relpath:
            folder = os.path.join(library_path, relpath.replace('/', os.sep))
            return folder
        return None

    def library_path_for_backup(self, db):
        """Resolve the current library root path for backup lookup."""
        for target in (db, getattr(self.gui, 'current_db', None)):
            if target is None:
                continue
            for attr in ('library_path', 'path'):
                try:
                    value = getattr(target, attr, None)
                    if isinstance(value, str) and value:
                        return value
                except Exception:
                    pass
            try:
                backend = getattr(target, 'backend', None)
                value = getattr(backend, 'library_path', None)
                if isinstance(value, str) and value:
                    return value
            except Exception:
                pass
        return None

    def annotate_image(self, image_data, number_text, p):
        """Draw the orange series badge on cover image bytes."""
        image = image_from_data(image_data)
        if image.isNull():
            return None, None

        image = image.convertToFormat(self.qimage_format_argb32())
        w, h = image.width(), image.height()
        if w <= 0 or h <= 0:
            return None, None

        painter = QPainter(image)
        painter.setRenderHint(self.painter_render_hint('Antialiasing'))
        painter.setRenderHint(self.painter_render_hint('TextAntialiasing'))

        badge_rect, inner_rect = self.compute_badge_layout(p, w, h)
        if badge_rect.width() <= 0 or badge_rect.height() <= 0:
            painter.end()
            return None, None

        font = self.fit_badge_font(painter, str(number_text or ''), inner_rect)
        self.draw_series_badge(painter, badge_rect, inner_rect, str(number_text or ''), font, bool(p.get('shadow_enabled', True)))
        painter.end()

        info = {
            'image': f'{w}x{h}',
            'font_size': font.pixelSize(),
            'badge': (badge_rect.x(), badge_rect.y(), badge_rect.width(), badge_rect.height()),
            'inner': (inner_rect.x(), inner_rect.y(), inner_rect.width(), inner_rect.height()),
        }
        return image, info

    def compute_badge_layout(self, p, w, h):
        """Compute badge geometry for one image."""
        margin = self.clamp_int(p.get('margin', 24), 0, max(w, h))
        short_side = max(1, min(w, h))
        requested_size = self.clamp_int(p.get('badge_size', 0), 0, short_side)
        if requested_size > 0:
            badge_size = requested_size
        else:
            percent = self.clamp_float(p.get('auto_badge_percent', 16.0), 4.0, 40.0)
            badge_size = int(round(short_side * percent / 100.0))
        badge_size = max(24, min(badge_size, max(24, short_side - 2 * margin)))

        x, y = self.position_for_badge(p.get('position', 'bottom_right'), w, h, badge_size, badge_size, margin)
        badge_rect = QRect(x, y, badge_size, badge_size)
        inner_margin = max(3, int(round(badge_size * 0.14)))
        inner_rect = QRect(
            x + inner_margin,
            y + inner_margin,
            max(1, badge_size - 2 * inner_margin),
            max(1, badge_size - 2 * inner_margin),
        )
        return badge_rect, inner_rect

    def fit_badge_font(self, painter, text, inner_rect):
        """Fit a bold number font inside the badge center."""
        font = QFont()
        font.setBold(True)
        target = max(10, int(round(inner_rect.height() * 0.72)))
        minimum = max(8, int(round(inner_rect.height() * 0.25)))
        for size in range(target, minimum - 1, -1):
            font.setPixelSize(size)
            painter.setFont(font)
            metrics = QFontMetrics(font)
            text_w = self.text_width(metrics, text)
            text_h = metrics.height()
            if text_w <= int(inner_rect.width() * 0.76) and text_h <= int(inner_rect.height() * 0.76):
                return font
        font.setPixelSize(minimum)
        return font

    def draw_series_badge(self, painter, badge_rect, inner_rect, text, font, shadow_enabled):
        """Render a scalloped orange badge with the series number."""
        badge_rect_f = QRectF(badge_rect)
        inner_rect_f = QRectF(inner_rect)
        outer_path = self.scalloped_badge_path(badge_rect_f, scallops=16)

        if shadow_enabled:
            shadow_path = QPainterPath(outer_path)
            offset = max(2.0, badge_rect_f.width() * 0.035)
            shadow_path.translate(offset, offset)
            painter.setPen(self.no_pen_flag())
            painter.setBrush(QColor(0, 0, 0, 70))
            painter.drawPath(shadow_path)

        gold_outer = QRadialGradient(badge_rect_f.center(), badge_rect_f.width() * 0.58, badge_rect_f.center())
        gold_outer.setColorAt(0.0, QColor('#FFD76A'))
        gold_outer.setColorAt(0.55, QColor('#F7B92F'))
        gold_outer.setColorAt(1.0, QColor('#D98606'))
        painter.setBrush(gold_outer)
        painter.setPen(QPen(QColor('#D48A00'), max(1, int(round(badge_rect_f.width() * 0.025)))))
        painter.drawPath(outer_path)

        ring_rect = QRectF(
            badge_rect_f.x() + badge_rect_f.width() * 0.10,
            badge_rect_f.y() + badge_rect_f.height() * 0.10,
            badge_rect_f.width() * 0.80,
            badge_rect_f.height() * 0.80,
        )
        painter.setBrush(self.no_brush_flag())
        painter.setPen(QPen(QColor(255, 240, 185, 220), max(1, int(round(badge_rect_f.width() * 0.020)))))
        painter.drawEllipse(ring_rect)

        gold_inner = QRadialGradient(inner_rect_f.center(), inner_rect_f.width() * 0.65, inner_rect_f.topLeft())
        gold_inner.setColorAt(0.0, QColor('#FFD86B'))
        gold_inner.setColorAt(0.75, QColor('#FDB62A'))
        gold_inner.setColorAt(1.0, QColor('#E59A0A'))
        painter.setBrush(gold_inner)
        painter.setPen(QPen(QColor('#CC8400'), max(1, int(round(badge_rect_f.width() * 0.012)))))
        painter.drawEllipse(inner_rect_f)

        highlight_rect = QRectF(inner_rect_f)
        highlight_rect.adjust(inner_rect_f.width() * 0.07, inner_rect_f.height() * 0.05, -inner_rect_f.width() * 0.07, -inner_rect_f.height() * 0.40)
        painter.setBrush(QColor(255, 255, 255, 45))
        painter.setPen(self.no_pen_flag())
        painter.drawEllipse(highlight_rect)

        painter.setFont(font)
        shadow_offset = max(1, int(round(inner_rect.height() * 0.03)))
        painter.setPen(QColor(255, 235, 170, 180))
        painter.drawText(QRect(inner_rect.x() + shadow_offset, inner_rect.y() + shadow_offset, inner_rect.width(), inner_rect.height()), self.align_center_flag(), text)
        painter.setPen(QColor('#4E2A00'))
        painter.drawText(inner_rect, self.align_center_flag(), text)

    def scalloped_badge_path(self, rect, scallops=16):
        """Build a simple scalloped seal outline path."""
        cx = rect.center().x()
        cy = rect.center().y()
        outer_r = min(rect.width(), rect.height()) / 2.0
        inner_r = outer_r * 0.92
        steps = max(12, int(scallops) * 2)
        path = QPainterPath()
        for i in range(steps):
            angle = (-math.pi / 2.0) + (2.0 * math.pi * i / steps)
            radius = outer_r if i % 2 == 0 else inner_r
            point = QPointF(cx + math.cos(angle) * radius, cy + math.sin(angle) * radius)
            if i == 0:
                path.moveTo(point)
            else:
                path.lineTo(point)
        path.closeSubpath()
        return path

    def position_for_badge(self, position, image_w, image_h, badge_w, badge_h, margin):
        """Compute the badge origin from the configured position."""
        pos_map = {
            'top_left': (margin, margin),
            'top_right': (image_w - badge_w - margin, margin),
            'bottom_left': (margin, image_h - badge_h - margin),
            'bottom_right': (image_w - badge_w - margin, image_h - badge_h - margin),
            'top_center': ((image_w - badge_w) // 2, margin),
            'bottom_center': ((image_w - badge_w) // 2, image_h - badge_h - margin),
            'center': ((image_w - badge_w) // 2, (image_h - badge_h) // 2),
        }
        x, y = pos_map.get(position, pos_map['bottom_right'])
        x = self.clamp_int(x, 0, max(0, image_w - badge_w))
        y = self.clamp_int(y, 0, max(0, image_h - badge_h))
        return x, y


    def format_series_index(self, series_index):
        """Format Calibre series numbers without losing decimals."""
        try:
            value = float(series_index)
        except Exception:
            return str(series_index)
        if value.is_integer():
            return str(int(value))
        return ('%.2f' % value).rstrip('0').rstrip('.')

    def resolve_output_format(self, original_bytes, requested):
        """Choose the output image format for the annotated cover."""
        requested = str(requested or 'original').lower()
        if requested == 'png':
            return 'PNG'
        if requested in ('jpeg', 'jpg'):
            return 'JPEG'
        detected = self.detect_image_extension(original_bytes)
        if detected == 'png':
            return 'PNG'
        return 'JPEG'

    def detect_image_extension(self, data):
        """Detect the source image type from its byte signature."""
        if data.startswith(b'\xff\xd8\xff'):
            return 'jpg'
        if data.startswith(b'\x89PNG\r\n\x1a\n'):
            return 'png'
        if data.startswith(b'RIFF') and b'WEBP' in data[:16]:
            return 'webp'
        return 'jpg'

    def safe_color(self, value, fallback):
        """Return a valid QColor with a fallback value."""
        color = QColor(str(value or fallback))
        if not color.isValid():
            color = QColor(fallback)
        return color

    def clamp_int(self, value, minimum, maximum):
        """Clamp a value to an integer range."""
        try:
            value = int(value)
        except Exception:
            value = minimum
        return max(minimum, min(maximum, value))

    def clamp_float(self, value, minimum, maximum):
        """Clamp a value to a floating-point range."""
        try:
            value = float(value)
        except Exception:
            value = minimum
        return max(minimum, min(maximum, value))

    def text_width(self, metrics, text):
        """Measure text width across Qt versions."""
        try:
            return metrics.horizontalAdvance(text)
        except Exception:
            return metrics.width(text)

    def qimage_format_argb32(self):
        """Return the Qt ARGB32 image format flag."""
        return getattr(getattr(QImage, 'Format', QImage), 'Format_ARGB32')

    def painter_render_hint(self, name):
        """Return a painter render hint across Qt versions."""
        hints = getattr(QPainter, 'RenderHint', QPainter)
        return getattr(hints, name, getattr(hints, 'Antialiasing'))

    def align_center_flag(self):
        """Return the Qt center-alignment flag."""
        return getattr(getattr(Qt, 'AlignmentFlag', Qt), 'AlignCenter')


    def no_brush_flag(self):
        """Return the Qt no-brush flag."""
        return getattr(getattr(Qt, 'BrushStyle', Qt), 'NoBrush')

    def no_pen_flag(self):
        """Return the Qt no-pen flag."""
        return getattr(getattr(Qt, 'PenStyle', Qt), 'NoPen')

    def exec_dialog(self, dialog):
        """Execute a dialog across Qt versions."""
        try:
            return dialog.exec()
        except AttributeError:
            return dialog.exec_()
