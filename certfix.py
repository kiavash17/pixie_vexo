"""Import this before any HTTPS/WebSocket use.

This machine's Windows certificate store holds a malformed certificate, so Python's
ssl.create_default_context() fails with "[ASN1: NOT_ENOUGH_DATA]". When no CA file is
given, use certifi's bundle instead of the Windows store.
"""
import ssl

import certifi

_original = ssl.create_default_context


def _create_default_context(purpose=ssl.Purpose.SERVER_AUTH, *, cafile=None, capath=None, cadata=None):
    if cafile is None and capath is None and cadata is None:
        cafile = certifi.where()
    return _original(purpose, cafile=cafile, capath=capath, cadata=cadata)


ssl.create_default_context = _create_default_context
ssl._create_default_https_context = _create_default_context   # used by urllib / http.client
