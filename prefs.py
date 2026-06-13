from calibre.utils.config import JSONConfig

# Calibre JSONConfig namespace used to store plugin preferences.
PREF_NAME = 'plugins/annotate_series_cover'

# Built-in preference defaults used when no user setting exists.
DEFAULTS = {
    'language': 'en',
    'position': 'bottom_right',
    'margin': 24,
    'badge_size': 0,
    'auto_badge_percent': 16.0,
    'shadow_enabled': True,
    'output_format': 'original',
}


def get_prefs():
    """Create the JSONConfig object with defaults attached."""
    cfg = JSONConfig(PREF_NAME)
    for key, value in DEFAULTS.items():
        cfg.defaults[key] = value
    return cfg


def current_prefs():
    """Return a plain dictionary of effective preferences."""
    cfg = get_prefs()
    data = dict(DEFAULTS)
    try:
        data.update(dict(cfg))
    except Exception:
        for key in DEFAULTS:
            try:
                data[key] = cfg.get(key, DEFAULTS[key])
            except Exception:
                pass
    return data


def save_prefs(values):
    """Write updated preference values to Calibre storage."""
    cfg = get_prefs()
    for key, value in values.items():
        cfg[key] = value
    try:
        cfg.commit()
    except Exception:
        pass
    return cfg
