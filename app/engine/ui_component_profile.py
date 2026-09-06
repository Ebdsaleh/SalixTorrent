"""SalixTorrent's application-level reusable-component layout profile.

Concrete dimensions live here instead of being scattered through view
construction code.  A future theme can derive from the same framework profile
and override these semantic slots without changing application behavior.
"""

from app.engine.components.layout import ControlLayoutDefaults
from app.engine.components.profile import ComponentLayoutProfile, FRAMEWORK_COMPONENT_PROFILE


SALIXTORRENT_COMPONENT_PROFILE = ComponentLayoutProfile(
    name="salixtorrent-desktop",
    parent=FRAMEWORK_COMPONENT_PROFILE,
    layouts={
        # Preferences.
        "settings.download_path": ControlLayoutDefaults(width=700),
        "settings.listen_port": ControlLayoutDefaults(width=100),
        "settings.protocol": ControlLayoutDefaults(width=220),
        "settings.max_peers": ControlLayoutDefaults(width=90),
        "settings.peer_encryption": ControlLayoutDefaults(width=190),
        "settings.network_interface": ControlLayoutDefaults(width=430),
        "settings.active_slots": ControlLayoutDefaults(width=90),
        "settings.queue_priority": ControlLayoutDefaults(width=130),
        "settings.bandwidth.value": ControlLayoutDefaults(width=110),
        "settings.bandwidth.unit": ControlLayoutDefaults(width=90),
        "settings.seeding_goal": ControlLayoutDefaults(width=230),
        "settings.seeding_ratio": ControlLayoutDefaults(width=120),
        "settings.seeding_duration.input": ControlLayoutDefaults(width=120),
        "settings.seeding_duration.grid": ControlLayoutDefaults(width=250),
        "settings.language": ControlLayoutDefaults(width=205),
        "settings.ui_text_size": ControlLayoutDefaults(width=180),
        "settings.documentation_scale": ControlLayoutDefaults(width=190),
        "settings.transfer_rate_display": ControlLayoutDefaults(width=105),
        # Torrent Properties / Configure targets.
        "torrent_properties.seeding_goal": ControlLayoutDefaults(width=230),
        "torrent_properties.seeding_ratio": ControlLayoutDefaults(width=110),
        "torrent_properties.seeding_time_part": ControlLayoutDefaults(width=58),
        "configure_targets.seeding_goal": ControlLayoutDefaults(width=250),
        "configure_targets.seeding_ratio": ControlLayoutDefaults(width=120),
        "configure_targets.duration.input": ControlLayoutDefaults(width=130),
        "configure_targets.duration.grid": ControlLayoutDefaults(width=280),
    },
    columns={
        "settings.seeding_duration.columns": (80, 150),
        "configure_targets.duration.columns": (90, 170),
    },
)
