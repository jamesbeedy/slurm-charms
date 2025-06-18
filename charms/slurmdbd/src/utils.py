#!/usr/bin/env python3
# Copyright (c) 2025 Vantage Compute Corporation
# See LICENSE file for licensing details.

"""utils.py."""

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def parse_user_supplied_parameters(custom_config: str) -> Dict[Any, Any]:
    """Parse the user supplied parameters."""
    user_supplied_parameters = {}

    try:
        for line in str(custom_config).splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                raise IndexError(f"Malformed config line (missing '='): {line}")
            key, value = line.split("=", 1)
            user_supplied_parameters[key.strip()] = value.strip()
    except IndexError as e:
        logger.error(f"Could not parse user supplied parameters: {e}.")
        raise e

    return user_supplied_parameters
