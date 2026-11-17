"""UUIDv7 primary keys (RFC 9562).

The first 48 bits are a millisecond timestamp, so new ids sort after old ones. That keeps
inserts appending to the end of InnoDB's clustered primary-key index instead of scattering
across it the way random UUIDv4 values would. Python gains ``uuid.uuid7`` in 3.14; until
we move there this small implementation is used.
"""

import os
import time
import uuid


def uuid7() -> uuid.UUID:
    timestamp_ms = time.time_ns() // 1_000_000
    value = (timestamp_ms & 0xFFFF_FFFF_FFFF) << 80
    value |= int.from_bytes(os.urandom(10), "big")  # 80 random bits
    value &= ~(0xF << 76)
    value |= 0x7 << 76  # version 7
    value &= ~(0x3 << 62)
    value |= 0x2 << 62  # RFC variant
    return uuid.UUID(int=value)
