from calibre.customize import InterfaceActionBase


class SeriesCoverStamper(InterfaceActionBase):
    """Calibre plugin metadata and configuration entry points."""
    # Public plugin metadata read by Calibre.
    # Internal plugin name shown by Calibre's plugin manager.
    name = 'Series Cover Stamper'
    description = 'Stamp series number on selected book covers'
    supported_platforms = ['windows', 'osx', 'linux']
    author = 'Gilles Macabies <macgile@gmail.com>'
    version = (1, 0, 0)
    minimum_calibre_version = (5, 0, 0)
    actual_plugin = 'calibre_plugins.annotate_series_cover.action:SeriesCoverStamperAction'

    def is_customizable(self):
        """Tell Calibre that this plugin exposes user settings."""
        return True

    def config_widget(self):
        """Create the Calibre-hosted configuration widget."""
        from calibre_plugins.annotate_series_cover.config_widget import ConfigWidget
        return ConfigWidget()

    def save_settings(self, config_widget):
        """Persist settings from the Calibre configuration dialog."""
        config_widget.save_settings()
