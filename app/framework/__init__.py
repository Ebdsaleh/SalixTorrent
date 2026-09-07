"""Provisional reusable framework boundary proven inside SalixTorrent.

Names and package structure remain internal working contracts until the wider
RAD/framework extraction is complete. Modules under this namespace must stay
independent of SalixTorrent views, BitTorrent logic, localization content and
concrete desktop backend adapters.

Intra-framework imports are package-relative so this directory can be copied
and renamed as one unit during extraction experiments. Backend-neutral
responsive coordination consumes an injected host contract; native resize
hooks remain in application/backend adapters. Backend-neutral rolling telemetry
and realtime plot coordination follow the same rule: data/model contracts live
here while concrete plotting remains adapter-owned. That portability is an
internal boundary guarantee only; it does not freeze a final package name,
version, or public API.
"""
