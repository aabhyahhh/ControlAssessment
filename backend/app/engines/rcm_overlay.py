"""
Non-destructive overlay accessor. The original uploaded RCM (controls table,
populated verbatim from the normalized upload) is never mutated in place;
every edit — inline, chat-driven, or LLM-inferred — is written to
control_overlays and merged in here. Every downstream read (risk scoring,
evidence matching, testing) must go through this accessor, never read
`controls` directly.
"""

from __future__ import annotations

from psycopg.rows import dict_row


def load_effective_controls(conn, project_id: str) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM controls WHERE project_id = %s ORDER BY control_id", (project_id,))
        controls = cur.fetchall()
        cur.execute(
            "SELECT control_id, field, new_value FROM control_overlays WHERE project_id = %s",
            (project_id,),
        )
        overlays = cur.fetchall()

    overlay_map: dict[str, dict[str, str]] = {}
    for o in overlays:
        overlay_map.setdefault(o["control_id"], {})[o["field"]] = o["new_value"]

    for c in controls:
        for field, value in overlay_map.get(c["control_id"], {}).items():
            if field in c:
                c[field] = value
            else:
                c.setdefault("raw_row", {})[field] = value

    return controls
