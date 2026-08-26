# app/views/transfer_rate.py

from __future__ import annotations

from typing import Iterable, Tuple


TRANSFER_RATE_UNITS = ("Auto", "KB/s", "MB/s", "kbps", "Mbps")


def normalize_transfer_rate_unit(value: object) -> str:
    unit = str(value or "Auto").strip()
    return unit if unit in TRANSFER_RATE_UNITS else "Auto"


def _safe_kib_per_second(value: object) -> float:
    try:
        return max(0.0, float(value or 0.0))
    except (TypeError, ValueError):
        return 0.0


def choose_auto_transfer_rate_unit(kib_per_second: object) -> str:
    value = _safe_kib_per_second(kib_per_second)
    return "MB/s" if value >= 1024.0 else "KB/s"


def transfer_rate_value(kib_per_second: object, unit: str) -> float:
    """Convert SalixTorrent's internal KiB/s telemetry to a display unit.

    The project historically calls this telemetry ``*_kbps`` even though it is
    byte-rate data measured in 1024-byte KiB/s. Keep that backend contract
    intact and convert only at the presentation boundary.
    """
    value = _safe_kib_per_second(kib_per_second)
    unit = normalize_transfer_rate_unit(unit)
    if unit == "Auto":
        unit = choose_auto_transfer_rate_unit(value)

    bytes_per_second = value * 1024.0
    if unit == "MB/s":
        return bytes_per_second / (1024.0 * 1024.0)
    if unit == "kbps":
        return bytes_per_second * 8.0 / 1000.0
    if unit == "Mbps":
        return bytes_per_second * 8.0 / 1_000_000.0
    return bytes_per_second / 1024.0


def format_transfer_rate(kib_per_second: object, unit: str = "Auto") -> str:
    normalized = normalize_transfer_rate_unit(unit)
    effective = (
        choose_auto_transfer_rate_unit(kib_per_second)
        if normalized == "Auto"
        else normalized
    )
    value = transfer_rate_value(kib_per_second, effective)

    if effective in {"MB/s", "Mbps"}:
        return f"{value:,.2f} {effective}"
    return f"{value:,.1f} {effective}"


def format_transfer_rate_pair(
    download_kib_per_second: object,
    upload_kib_per_second: object,
    unit: str = "Auto",
) -> str:
    normalized = normalize_transfer_rate_unit(unit)
    if normalized == "Auto":
        normalized = choose_auto_transfer_rate_unit(
            max(
                _safe_kib_per_second(download_kib_per_second),
                _safe_kib_per_second(upload_kib_per_second),
            )
        )

    down = transfer_rate_value(download_kib_per_second, normalized)
    up = transfer_rate_value(upload_kib_per_second, normalized)
    if normalized in {"MB/s", "Mbps"}:
        return f"{down:,.2f} / {up:,.2f} {normalized}"
    return f"{down:,.1f} / {up:,.1f} {normalized}"


def choose_plot_unit(values: Iterable[object], requested_unit: str) -> str:
    normalized = normalize_transfer_rate_unit(requested_unit)
    if normalized != "Auto":
        return normalized

    peak = 0.0
    for value in values:
        peak = max(peak, _safe_kib_per_second(value))
    return choose_auto_transfer_rate_unit(peak)


def convert_plot_values(
    values: Iterable[object], requested_unit: str
) -> Tuple[list[float], str]:
    raw = list(values)
    effective = choose_plot_unit(raw, requested_unit)
    return [transfer_rate_value(value, effective) for value in raw], effective
