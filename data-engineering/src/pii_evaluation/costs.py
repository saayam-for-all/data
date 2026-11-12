"""Monthly cost estimates for running PII detection in Lambda.

Prices are AWS on-demand list prices for US East (N. Virginia), taken from the
public AWS Price List API (no account needed):

* Comprehend ``DetectPiiEntities``: USD 0.0001 per unit (first 10M units/month).
  One unit is 100 characters with a 3-unit minimum per request.
  Offer file published 2026-09-11.
* Lambda x86: USD 0.0000166667 per GB-second and USD 0.20 per million requests.
  Offer file published 2026-10-30.

Free tiers are deliberately not subtracted, so estimates are upper bounds.
"""

from __future__ import annotations

import math
from typing import Iterable

COMPREHEND_PRICE_PER_UNIT_USD = 0.0001
COMPREHEND_UNIT_CHARACTERS = 100
COMPREHEND_MINIMUM_UNITS = 3
LAMBDA_PRICE_PER_GB_SECOND_USD = 0.0000166667
LAMBDA_PRICE_PER_REQUEST_USD = 0.20 / 1_000_000


def comprehend_units(characters: int) -> int:
    """Billable units for one ``DetectPiiEntities`` call on ``characters`` characters."""
    if characters < 0:
        raise ValueError("characters cannot be negative")
    return max(COMPREHEND_MINIMUM_UNITS, math.ceil(characters / COMPREHEND_UNIT_CHARACTERS))


def comprehend_monthly_cost(
    text_lengths: Iterable[int],
    requests_per_month: int,
    calls_per_request: int = 1,
) -> float:
    """Comprehend cost for a month, using the average units of ``text_lengths``.

    ``calls_per_request`` is 1 when subject and description are sent together
    and 2 when they are sent as separate calls (each pays the 3-unit minimum).
    """
    if requests_per_month < 0 or calls_per_request < 1:
        raise ValueError("requests_per_month must be >= 0 and calls_per_request >= 1")
    lengths = list(text_lengths)
    if not lengths:
        raise ValueError("at least one text length is required")
    average_units = sum(comprehend_units(length) for length in lengths) / len(lengths)
    return average_units * calls_per_request * requests_per_month * COMPREHEND_PRICE_PER_UNIT_USD


def lambda_compute_cost(seconds_per_request: float, requests_per_month: int,
                        memory_mb: int = 512) -> float:
    """Lambda duration cost of the extra time spent on PII detection.

    Invocation charges are excluded because detection runs inside an archive
    Lambda that is invoked anyway.
    """
    if seconds_per_request < 0 or requests_per_month < 0 or memory_mb <= 0:
        raise ValueError("inputs must be non-negative and memory_mb positive")
    gb_seconds = seconds_per_request * requests_per_month * memory_mb / 1024
    return gb_seconds * LAMBDA_PRICE_PER_GB_SECOND_USD
