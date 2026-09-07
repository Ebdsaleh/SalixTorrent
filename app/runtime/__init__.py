"""Provisional reusable application-runtime boundary.

This package contains backend-neutral runtime mechanics extracted from the
working SalixTorrent application.  Names and package structure remain working
contracts until the wider engine/framework boundary is proven with additional
applications and presentation backends.

Modules here must remain usable without Dear PyGui, SalixTorrent views or
BitTorrent protocol code.
"""
