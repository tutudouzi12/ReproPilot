"""Bits and bytes related humanization."""

from __future__ import annotations

from math import log

from humanize.i18n import _gettext as _

suffixes = {
    "decimal": (
        "kB",
        "MB",
        "GB",
        "TB",
        "PB",
        "EB",
        "ZB",
        "YB",
        "RB",
        "QB",
    ),
    "binary": (
        "KiB",
        "MiB",
        "GiB",
        "TiB",
        "PiB",
        "EiB",
        "ZiB",
        "YiB",
        "RiB",
        "QiB",
    ),
    "gnu": "KMGTPEZYRQ",
}


def naturalsize(
    value: float | str,
    binary: bool = False,
    gnu: bool = False,
    format: str = "%.1f",
) -> str:
    """Format a number of bytes like a human-readable filesize (e.g. 10 kB).

    By default, decimal suffixes (kB, MB) are used.

    Non-GNU modes are compatible with jinja2's `filesizeformat` filter.

    Examples:
        ```pycon
        >>> naturalsize(3000000)
        '3.0 MB'
        >>> naturalsize(300, False, True)
        '300B'
        >>> naturalsize(3000, False, True)
        '2.9K'
        >>> naturalsize(3000, False, True, "%.3f")
        '2.930K'
        >>> naturalsize(3000, True)
        '2.9 KiB'
        >>> naturalsize(10**28)
        '10.0 RB'
        >>> naturalsize(10**34 * 3)
        '30000.0 QB'
        >>> naturalsize(-4096, True)
        '-4.0 KiB'

        ```

    Args:
        value (int, float, str): Integer to convert.
        binary (bool): If `True`, uses binary suffixes (KiB, MiB) with base
            2<sup>10</sup> instead of 10<sup>3</sup>.
        gnu (bool): If `True`, the binary argument is ignored and GNU-style
            (`ls -sh` style) prefixes are used (K, M) with the 2**10 definition.
        format (str): Custom formatter.

    Returns:
        str: Human readable representation of a filesize.
    """
    if gnu:
        suffix = suffixes["gnu"]
    elif binary:
        suffix = suffixes["binary"]
    else:
        suffix = suffixes["decimal"]

    base = 1024 if (gnu or binary) else 1000
    bytes_ = float(value)
    abs_bytes = abs(bytes_)

    if abs_bytes == 1 and not gnu:
        return _("%d Byte") % int(bytes_)

    if abs_bytes < base:
        return f"{int(bytes_)}B" if gnu else _("%d Bytes") % int(bytes_)

    # Calculate initial exponent
    exp = int(min(log(abs_bytes, base), len(suffix)))
    
    # Check if we're at the max possible exponent to avoid index errors
    if exp >= len(suffix):
        exp = len(suffix)
    
    # Calculate the value at this exponent
    unit_value = bytes_ / (base ** exp)
    
    # Format the value according to the format string
    formatted_value_str = format % unit_value
    formatted_value = float(formatted_value_str)
    
    # Check if the formatted value rounds up to the next threshold
    # For decimal: if it rounds to 1000.0, we should go to the next unit
    # For binary/GNU: if it rounds to 1024.0, we should go to the next unit
    threshold = base
    
    # If the formatted value is >= threshold, we need to increment the exponent
    # But make sure we don't exceed the available suffixes
    if abs(formatted_value) >= threshold and exp < len(suffix):
        exp += 1
        if exp <= len(suffix):
            # Recalculate the value with the new exponent
            unit_value = bytes_ / (base ** exp)
            formatted_value_str = format % unit_value
    elif exp > 0 and exp <= len(suffix):
        # Use the original calculation but ensure we don't go below 0
        pass
    
    # Adjust exp for suffix indexing (original logic was exp - 1)
    if exp == 0:
        return f"{int(bytes_)}B" if gnu else _("%d Bytes") % int(bytes_)
    
    space = "" if gnu else " "
    
    # Make sure exp-1 doesn't go out of bounds
    if exp - 1 < len(suffix):
        ret: str = formatted_value_str + space + _(suffix[exp - 1])
    else:
        # If we've exceeded available suffixes, just use the highest one
        highest_exp = min(len(suffix), exp)
        if highest_exp > 0:
            final_unit_value = bytes_ / (base ** highest_exp)
            formatted_final = format % final_unit_value
            ret: str = formatted_final + space + _(suffix[highest_exp - 1])
        else:
            ret: str = formatted_value_str + space + suffix[-1]  # fallback
    
    return ret
