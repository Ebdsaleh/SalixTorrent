# app/logic/tracker_scrape.py

from __future__ import annotations

import asyncio
import random
import socket
import struct
import time
import urllib.parse
from collections import defaultdict
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import aiohttp

from app.logic.bencode import Bencode
from app.logic.network_binding import ip_family, normalise_bind_address


SCRAPE_REFRESH_INTERVAL = 15 * 60.0
SCRAPE_COALESCE_SECONDS = 2.0
HTTP_SCRAPE_BATCH_SIZE = 20
# BEP-15 says roughly 74 hashes fit in one scrape datagram. Keep comfortably
# below a typical Ethernet MTU so the request normally avoids IP fragmentation.
UDP_SCRAPE_BATCH_SIZE = 60
MAX_CONCURRENT_SCRAPE_TRACKERS = 4


class TrackerScrapeError(RuntimeError):
    pass


class TrackerScrapeUnsupported(TrackerScrapeError):
    pass


def derive_http_scrape_url(announce_url: str) -> Optional[str]:
    """Return the BEP-48 scrape endpoint for an HTTP(S) announce URL.

    BEP-48 defines the endpoint by replacing ``announce`` in the URL path. A
    tracker URL without that path component has no standards-defined scrape
    endpoint, so SalixTorrent does not guess one.
    """
    parsed = urllib.parse.urlsplit(str(announce_url or ""))
    if parsed.scheme.lower() not in {"http", "https"}:
        return None
    path = parsed.path or ""
    index = path.rfind("announce")
    if index < 0:
        return None
    scrape_path = path[:index] + "scrape" + path[index + len("announce"):]
    # URL fragments are client-side identifiers and are never part of a
    # tracker HTTP request. Do not carry one into the generated scrape URL.
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, scrape_path, parsed.query, "")
    )


def _chunks(values: Sequence[Any], size: int):
    for index in range(0, len(values), max(1, int(size))):
        yield values[index:index + max(1, int(size))]


def _decode_scrape_stats(value: Any) -> dict:
    if not isinstance(value, dict):
        raise TrackerScrapeError("Malformed tracker scrape statistics")

    def number(key: bytes) -> int:
        try:
            return max(0, int(value.get(key, 0) or 0))
        except (TypeError, ValueError):
            return 0

    return {
        "seeders": number(b"complete"),
        "leechers": number(b"incomplete"),
        "completed": number(b"downloaded"),
    }


def decode_http_scrape_response(payload: bytes) -> Dict[bytes, dict]:
    decoded = Bencode.decode(payload)
    if not isinstance(decoded, dict):
        raise TrackerScrapeError("Malformed HTTP scrape response")

    failure = decoded.get(b"failure reason") or decoded.get(b"failure_reason")
    if failure:
        if isinstance(failure, bytes):
            failure = failure.decode("utf-8", errors="replace")
        raise TrackerScrapeError(str(failure))

    files = decoded.get(b"files")
    if not isinstance(files, dict):
        raise TrackerScrapeError("HTTP scrape response did not contain a files dictionary")

    out: Dict[bytes, dict] = {}
    for info_hash, stats in files.items():
        if isinstance(info_hash, bytes) and len(info_hash) == 20:
            out[info_hash] = _decode_scrape_stats(stats)
    return out


class TrackerScrapeCoordinator:
    """One shared, timer-driven scrape coordinator for the whole application.

    Active torrents are grouped by tracker URL, allowing one BEP-48 HTTP scrape
    or BEP-15 UDP scrape to carry multiple info-hashes. Results are cached in
    each session's existing TrackerClient source record; the UI never initiates
    tracker traffic merely because a view is being rendered.
    """

    def __init__(
        self,
        sessions_provider: Callable[[], Iterable[Any]],
        *,
        bind_address: str = "",
        refresh_interval: float = SCRAPE_REFRESH_INTERVAL,
    ):
        self._sessions_provider = sessions_provider
        self.bind_address = normalise_bind_address(bind_address)
        self.refresh_interval = max(60.0, float(refresh_interval))
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._timer: Optional[asyncio.TimerHandle] = None
        self._task: Optional[asyncio.Task] = None
        self._refresh_again = False
        self._closed = False

    def start(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop
        self._closed = False
        self._schedule(SCRAPE_COALESCE_SECONDS)

    def close(self):
        self._closed = True
        self._refresh_again = False
        timer = self._timer
        self._timer = None
        if timer is not None:
            timer.cancel()
        task = self._task
        self._task = None
        if task is not None and not task.done():
            task.cancel()

    def set_bind_address(self, bind_address: str):
        self.bind_address = normalise_bind_address(bind_address)
        self.request_refresh(delay=0.5)

    def request_refresh(self, *, delay: float = SCRAPE_COALESCE_SECONDS):
        loop = self._loop
        if self._closed or loop is None or loop.is_closed():
            return
        try:
            loop.call_soon_threadsafe(self._schedule, max(0.0, float(delay)))
        except RuntimeError:
            return

    def _schedule(self, delay: float):
        if self._closed or self._loop is None or self._loop.is_closed():
            return
        when = self._loop.time() + max(0.0, float(delay))
        if self._timer is not None and not self._timer.cancelled():
            # Keep an already scheduled earlier refresh. This lets frequent UI
            # or lifecycle events coalesce instead of postponing or duplicating
            # network work.
            if self._timer.when() <= when:
                return
            self._timer.cancel()
        self._timer = self._loop.call_at(when, self._launch_refresh)

    def _launch_refresh(self):
        self._timer = None
        if self._closed:
            return
        if self._task is not None and not self._task.done():
            # A lifecycle/settings event arrived while the shared scrape was in
            # flight. Remember one coalesced follow-up rather than losing it or
            # launching an overlapping scrape task.
            self._refresh_again = True
            return
        self._task = asyncio.create_task(self._refresh_all(), name="SalixTrackerScrape")
        self._task.add_done_callback(self._refresh_done)

    def _refresh_done(self, task: asyncio.Task):
        if task is self._task:
            self._task = None
        if self._closed:
            return
        try:
            task.result()
        except asyncio.CancelledError:
            return
        except Exception as exc:
            # Scrapes are supplemental statistics and must never make a torrent
            # fail. Per-source errors are recorded below; this is only a guard
            # for unexpected coordinator-level errors.
            print(f"[Salix_T Notice] Tracker scrape refresh failed: {exc}")
        if self._refresh_again:
            self._refresh_again = False
            self._schedule(0.5)
        elif self._eligible_sessions():
            self._schedule(self.refresh_interval)

    def _eligible_sessions(self) -> List[Any]:
        try:
            sessions = list(self._sessions_provider() or [])
        except Exception:
            return []
        active_states = {"Checking", "Fast Resume", "Downloading", "Seeding"}
        return [
            session for session in sessions
            if bool(getattr(session, "is_running", False))
            and str(getattr(session, "state", "")) in active_states
        ]

    async def _refresh_all(self):
        sessions = self._eligible_sessions()
        if not sessions:
            return

        groups: Dict[str, List[Tuple[Any, str, bytes]]] = defaultdict(list)
        for session in sessions:
            torrent = getattr(session, "torrent", None)
            active_generations = tuple(getattr(session, "active_generations", ()) or ())
            swarm_hashes = dict(getattr(session, "swarm_hashes", {}) or {})
            if not active_generations:
                info_hash = getattr(torrent, "info_hash", b"")
                if isinstance(info_hash, bytes) and len(info_hash) == 20:
                    active_generations = ("v1",)
                    swarm_hashes = {"v1": info_hash}
            for generation in active_generations:
                info_hash = swarm_hashes.get(generation, b"")
                if not isinstance(info_hash, bytes) or len(info_hash) != 20:
                    continue
                for tracker_url in list(getattr(torrent, "announce_list", []) or []):
                    url = str(tracker_url or "")
                    if url.startswith(("http://", "https://", "udp://")):
                        groups[url].append((session, str(generation), info_hash))

        if not groups:
            return

        semaphore = asyncio.Semaphore(MAX_CONCURRENT_SCRAPE_TRACKERS)

        async def run_group(tracker_url: str, entries: List[Tuple[Any, str, bytes]]):
            async with semaphore:
                await self._scrape_group(tracker_url, entries)

        await asyncio.gather(
            *(run_group(url, entries) for url, entries in groups.items())
        )

    @staticmethod
    def _apply(session: Any, generation: str, tracker_url: str, result: dict):
        try:
            apply_method = getattr(session, "apply_tracker_scrape_result", None)
            if callable(apply_method):
                try:
                    apply_method(tracker_url, result, generation=generation)
                except TypeError:
                    apply_method(tracker_url, result)
            else:
                trackers = getattr(session, "_trackers_by_generation", {}) or {}
                tracker = trackers.get(generation) or getattr(session, "tracker", None)
                if tracker is not None:
                    tracker.apply_scrape_result(tracker_url, result)
        except Exception:
            pass

    async def _scrape_group(self, tracker_url: str, entries: List[Tuple[Any, str, bytes]]):
        # Hybrid sessions contribute one independently addressed swarm per
        # generation. Preserve both even when they belong to the same session.
        by_hash: Dict[bytes, List[Tuple[Any, str]]] = defaultdict(list)
        for session, generation, info_hash in entries:
            target = (session, generation)
            if target not in by_hash[info_hash]:
                by_hash[info_hash].append(target)
        hashes = list(by_hash)
        protocol = urllib.parse.urlsplit(tracker_url).scheme.lower()

        started = time.monotonic()
        try:
            if protocol in {"http", "https"}:
                endpoint = derive_http_scrape_url(tracker_url)
                if not endpoint:
                    raise TrackerScrapeUnsupported(
                        "Tracker announce URL has no standards-defined HTTP scrape endpoint"
                    )
                results = await self._scrape_http(endpoint, hashes)
            elif protocol == "udp":
                endpoint = tracker_url
                results = await asyncio.to_thread(self._scrape_udp_blocking, tracker_url, hashes)
            else:
                raise TrackerScrapeUnsupported("Tracker protocol does not support scraping")

            elapsed_ms = max(0.0, (time.monotonic() - started) * 1000.0)
            batch_size = len(hashes)
            for info_hash, sessions_for_hash in by_hash.items():
                stats = results.get(info_hash)
                if stats is None:
                    result = {
                        "status": "No Data",
                        "protocol": protocol.upper(),
                        "endpoint": endpoint,
                        "response_ms": elapsed_ms,
                        "batch_size": batch_size,
                        "error": "Tracker scrape succeeded but returned no statistics for this info hash",
                    }
                else:
                    result = {
                        "status": "Active",
                        "protocol": protocol.upper(),
                        "endpoint": endpoint,
                        "response_ms": elapsed_ms,
                        "batch_size": batch_size,
                        **stats,
                    }
                for session, generation in sessions_for_hash:
                    self._apply(session, generation, tracker_url, result)

        except asyncio.CancelledError:
            raise
        except TrackerScrapeUnsupported as exc:
            result = {
                "status": "Unsupported",
                "protocol": protocol.upper(),
                "endpoint": derive_http_scrape_url(tracker_url) or tracker_url,
                "response_ms": max(0.0, (time.monotonic() - started) * 1000.0),
                "batch_size": len(hashes),
                "error": str(exc),
            }
            for session, generation, _info_hash in entries:
                self._apply(session, generation, tracker_url, result)
        except (asyncio.TimeoutError, TimeoutError, socket.timeout) as exc:
            result = {
                "status": "Timeout",
                "protocol": protocol.upper(),
                "endpoint": derive_http_scrape_url(tracker_url) or tracker_url,
                "response_ms": max(0.0, (time.monotonic() - started) * 1000.0),
                "batch_size": len(hashes),
                "error": str(exc) or "Tracker scrape timed out",
            }
            for session, generation, _info_hash in entries:
                self._apply(session, generation, tracker_url, result)
        except Exception as exc:
            result = {
                "status": "Error",
                "protocol": protocol.upper(),
                "endpoint": derive_http_scrape_url(tracker_url) or tracker_url,
                "response_ms": max(0.0, (time.monotonic() - started) * 1000.0),
                "batch_size": len(hashes),
                "error": str(exc) or exc.__class__.__name__,
            }
            for session, generation, _info_hash in entries:
                self._apply(session, generation, tracker_url, result)

    async def _scrape_http(self, endpoint: str, info_hashes: Sequence[bytes]) -> Dict[bytes, dict]:
        parsed = urllib.parse.urlsplit(endpoint)
        host = parsed.hostname
        if not host:
            raise TrackerScrapeError("HTTP scrape tracker host is missing")

        family = ip_family(self.bind_address) if self.bind_address else socket.AF_UNSPEC
        connector_kwargs = {"family": family}
        if self.bind_address:
            connector_kwargs["local_addr"] = (self.bind_address, 0)

        timeout = aiohttp.ClientTimeout(total=8)
        connector = aiohttp.TCPConnector(**connector_kwargs)
        out: Dict[bytes, dict] = {}
        async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
            for batch in _chunks(list(info_hashes), HTTP_SCRAPE_BATCH_SIZE):
                params = "&".join(
                    "info_hash=" + urllib.parse.quote_from_bytes(info_hash, safe="")
                    for info_hash in batch
                )
                separator = "&" if parsed.query else "?"
                url = endpoint + separator + params
                async with session.get(url) as response:
                    if response.status != 200:
                        raise TrackerScrapeError(f"HTTP scrape returned status {response.status}")
                    payload = await response.read()
                out.update(decode_http_scrape_response(payload))
        return out

    def _scrape_udp_blocking(self, tracker_url: str, info_hashes: Sequence[bytes]) -> Dict[bytes, dict]:
        parsed = urllib.parse.urlsplit(tracker_url)
        host = parsed.hostname
        port = parsed.port or 80
        if not host:
            raise TrackerScrapeError("UDP scrape tracker host is missing")

        family = ip_family(self.bind_address) if self.bind_address else socket.AF_UNSPEC
        try:
            infos = socket.getaddrinfo(
                host, port, family, socket.SOCK_DGRAM, socket.IPPROTO_UDP
            )
        except OSError as exc:
            raise TrackerScrapeError(f"Could not resolve UDP scrape tracker: {exc}") from exc

        candidates = []
        seen = set()
        for af, socktype, proto, _canonname, sockaddr in infos:
            if af not in {socket.AF_INET, socket.AF_INET6}:
                continue
            key = (af, str(sockaddr[0]), int(sockaddr[1]))
            if key in seen:
                continue
            seen.add(key)
            candidates.append((af, socktype, proto, sockaddr))
        if not candidates:
            raise TrackerScrapeError("UDP scrape tracker has no usable IPv4/IPv6 address")

        last_error: Optional[BaseException] = None
        for af, socktype, proto, sockaddr in candidates:
            try:
                return self._scrape_udp_endpoint(af, socktype, proto, sockaddr, info_hashes)
            except (OSError, socket.timeout, TrackerScrapeError) as exc:
                last_error = exc
        if isinstance(last_error, TrackerScrapeError):
            raise last_error
        if isinstance(last_error, socket.timeout):
            raise last_error
        raise TrackerScrapeError(str(last_error or "UDP scrape tracker did not respond"))

    def _scrape_udp_endpoint(
        self,
        family: int,
        socktype: int,
        proto: int,
        sockaddr,
        info_hashes: Sequence[bytes],
    ) -> Dict[bytes, dict]:
        sock = socket.socket(family, socktype, proto)
        sock.settimeout(5.0)
        if self.bind_address:
            if ip_family(self.bind_address) != family:
                sock.close()
                raise TrackerScrapeError("Selected network bind address does not match scrape tracker family")
            bind_endpoint = (
                (self.bind_address, 0, 0, 0)
                if family == socket.AF_INET6 else (self.bind_address, 0)
            )
            sock.bind(bind_endpoint)

        try:
            connect_tx = random.randint(0, 0x7FFFFFFF)
            sock.sendto(struct.pack(">QII", 0x41727101980, 0, connect_tx), sockaddr)
            response, _ = sock.recvfrom(4096)
            if len(response) < 8:
                raise TrackerScrapeError("Short UDP connect response")
            action, transaction = struct.unpack(">II", response[:8])
            if action == 3:
                message = response[8:].decode("utf-8", errors="replace")
                raise TrackerScrapeError(message or "UDP tracker error")
            if len(response) < 16:
                raise TrackerScrapeError("Short UDP connect response")
            action, transaction, connection_id = struct.unpack(">IIQ", response[:16])
            if action != 0 or transaction != connect_tx:
                raise TrackerScrapeError("Invalid UDP connect response")

            out: Dict[bytes, dict] = {}
            for batch in _chunks(list(info_hashes), UDP_SCRAPE_BATCH_SIZE):
                tx = random.randint(0, 0x7FFFFFFF)
                packet = struct.pack(">QII", connection_id, 2, tx) + b"".join(batch)
                sock.sendto(packet, sockaddr)
                response, _ = sock.recvfrom(64 * 1024)
                if len(response) < 8:
                    raise TrackerScrapeError("Short UDP scrape response")
                action, transaction = struct.unpack(">II", response[:8])
                if action == 3:
                    message = response[8:].decode("utf-8", errors="replace")
                    raise TrackerScrapeError(message or "UDP tracker scrape error")
                if action != 2 or transaction != tx:
                    raise TrackerScrapeError("Invalid UDP scrape response")
                expected = 8 + (12 * len(batch))
                if len(response) < expected:
                    raise TrackerScrapeError("Short UDP scrape statistics response")
                offset = 8
                for info_hash in batch:
                    seeders, completed, leechers = struct.unpack(">III", response[offset:offset + 12])
                    out[info_hash] = {
                        "seeders": int(seeders),
                        "leechers": int(leechers),
                        "completed": int(completed),
                    }
                    offset += 12
            return out
        finally:
            sock.close()


