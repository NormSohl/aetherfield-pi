"""One sample from an AirGradient monitor's local server.

The rule that matters: a missing measurement is None, never 0. A dead CO2 sensor
logged as 0 ppm would look like the cleanest air in the building, in the chart and
in the record forever.
"""

# Stored as columns, in this order. Names are the local server's own.
FIELDS = (
    "pm01",
    "pm02",
    "pm10",
    "pm02Compensated",
    "pm003Count",
    "rco2",
    "atmp",
    "atmpCompensated",
    "rhum",
    "rhumCompensated",
    "tvocIndex",
    "noxIndex",
    "tvocRaw",
    "noxRaw",
    "wifi",
)


def number(value):
    """A float, or None. Accepts JSON numbers, quoted numbers and null.

    One odd field must not cost the other twenty, so nothing here raises.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        # NaN and the infinities can't round-trip through JSON or a chart.
        return float(value) if value == value and abs(value) != float("inf") else None
    if isinstance(value, str):
        try:
            return number(float(value))
        except ValueError:
            return None
    return None


def parse(payload):
    """Measurements and device identity from a /measures/current body."""
    if not isinstance(payload, dict):
        raise ValueError("expected a JSON object from the monitor")
    values = {name: number(payload.get(name)) for name in FIELDS}
    device = {
        name: payload[name]
        for name in ("serialno", "firmware", "model")
        if isinstance(payload.get(name), str)
    }
    return values, device
