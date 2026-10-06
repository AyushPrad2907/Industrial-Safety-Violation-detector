from typing import List, Tuple, Optional

def parse_zone_polygon(zone_str: str) -> Tuple[Optional[List[Tuple[float, float]]], Optional[str]]:
    """
    Parses a string of normalized polygon coordinates formatted like:
    "0.6,0.2;0.95,0.2;0.95,0.9;0.6,0.9"

    Returns:
        (points, None) on success, where points is a list of (x, y) float tuples.
        (None, error_message) on validation failure.
    """
    if not zone_str or not zone_str.strip():
        return None, "Zone coordinate input is empty."

    raw_pairs = [p.strip() for p in zone_str.strip().split(";") if p.strip()]
    
    if len(raw_pairs) < 3:
        return None, f"Polygon requires at least 3 vertices, but only {len(raw_pairs)} found."

    points: List[Tuple[float, float]] = []
    for idx, pair in enumerate(raw_pairs, start=1):
        parts = [coord.strip() for coord in pair.split(",") if coord.strip()]
        if len(parts) != 2:
            return None, f"Point #{idx} ('{pair}') must have exactly two values separated by a comma (x, y)."
        try:
            x = float(parts[0])
            y = float(parts[1])
        except ValueError:
            return None, f"Point #{idx} ('{pair}') contains invalid non-numeric coordinates."

        if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
            return None, f"Point #{idx} ({x}, {y}) coordinates must be normalized between 0.0 and 1.0."

        points.append((x, y))

    return points, None
