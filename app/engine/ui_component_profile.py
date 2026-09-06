"""SalixTorrent's application-level reusable-component layout profile.

Concrete dimensions live here instead of being scattered through view
construction code.  A future theme can derive from the same framework profile
and override these semantic slots without changing application behavior.
"""

from app.engine.components.layout import FILL, ControlLayoutDefaults
from app.engine.components.profile import ComponentLayoutProfile, FRAMEWORK_COMPONENT_PROFILE


SALIXTORRENT_COMPONENT_PROFILE = ComponentLayoutProfile(
    name="salixtorrent-desktop",
    parent=FRAMEWORK_COMPONENT_PROFILE,
    layouts={
        # Preferences structural regions.
        "settings.downloads_panel": ControlLayoutDefaults(width=FILL, height=112),
        "settings.networking_panel": ControlLayoutDefaults(width=530, height=290),
        "settings.connectivity_panel": ControlLayoutDefaults(width=FILL, height=360),
        "settings.privacy_panel": ControlLayoutDefaults(width=FILL, height=238),
        "settings.queue_panel": ControlLayoutDefaults(width=530, height=225),
        "settings.global_bandwidth_panel": ControlLayoutDefaults(width=FILL, height=225),
        "settings.new_defaults_panel": ControlLayoutDefaults(width=530, height=350),
        "settings.desktop_panel": ControlLayoutDefaults(width=FILL, height=350),
        # Preferences controls.
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
        # Create Torrent form structure and controls.
        "create_torrent.source_panel": ControlLayoutDefaults(width=FILL, height=155),
        "create_torrent.output_panel": ControlLayoutDefaults(width=FILL, height=190),
        "create_torrent.trackers_panel": ControlLayoutDefaults(width=FILL, height=175),
        "create_torrent.progress_panel": ControlLayoutDefaults(width=FILL, height=145),
        "create_torrent.section_gap": ControlLayoutDefaults(height=8),
        "create_torrent.generation": ControlLayoutDefaults(width=235),
        "create_torrent.piece_size": ControlLayoutDefaults(width=130),
        "create_torrent.comment": ControlLayoutDefaults(width=FILL),
        "create_torrent.trackers_input": ControlLayoutDefaults(width=FILL, height=105),
        "create_torrent.progress_bar": ControlLayoutDefaults(width=FILL, height=22),
        # Transfer utility dialogs.
        "download.magnet.dialog": ControlLayoutDefaults(width=680, height=285),
        "download.magnet.input": ControlLayoutDefaults(width=FILL, height=70),
        "download.magnet.progress": ControlLayoutDefaults(width=FILL),
        "download.remove.dialog": ControlLayoutDefaults(width=520, height=230),
        "download.removal_notice.dialog": ControlLayoutDefaults(width=520, height=170),
        "download.recheck.dialog": ControlLayoutDefaults(width=560, height=190),
        "download.completion_notice.dialog": ControlLayoutDefaults(width=480, height=150),
        # Torrent Properties / Configure targets.
        "configure_targets.dialog": ControlLayoutDefaults(width=620, height=365),
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
