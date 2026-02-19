"""Une filas duplicadas de sat_cfdi (mismo UUID, distinta capitalización).
Copia subtotal, impuestos desde la fila con más datos a la fila que muestra el portal."""
import os
import sqlite3

DB_PATH = os.getenv("APP_DB_PATH", "invoicing.db")

def main():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")

    # Actualizar filas que tienen total pero no subtotal/impuestos,
    # copiando desde la fila duplicada (mismo UUID case-insensitive) que sí los tenga
    conn.execute("""
        UPDATE sat_cfdi SET
            subtotal = COALESCE(
                (SELECT s2.subtotal FROM sat_cfdi s2
                 WHERE UPPER(s2.uuid) = UPPER(sat_cfdi.uuid)
                   AND s2.issuer_id = sat_cfdi.issuer_id
                   AND s2.direction = sat_cfdi.direction
                   AND s2.subtotal IS NOT NULL
                 LIMIT 1),
                subtotal
            ),
            impuestos = COALESCE(
                (SELECT s2.impuestos FROM sat_cfdi s2
                 WHERE UPPER(s2.uuid) = UPPER(sat_cfdi.uuid)
                   AND s2.issuer_id = sat_cfdi.issuer_id
                   AND s2.direction = sat_cfdi.direction
                   AND s2.impuestos IS NOT NULL
                 LIMIT 1),
                impuestos
            )
        WHERE subtotal IS NULL OR impuestos IS NULL
    """)

    # Copiar xml_path de la fila parseada a la de metadata si falta
    conn.execute("""
        UPDATE sat_cfdi SET xml_path = (
            SELECT s2.xml_path FROM sat_cfdi s2
            WHERE UPPER(s2.uuid) = UPPER(sat_cfdi.uuid)
              AND s2.issuer_id = sat_cfdi.issuer_id
              AND s2.direction = sat_cfdi.direction
              AND s2.xml_path IS NOT NULL AND s2.xml_path != ''
            LIMIT 1
        )
        WHERE (xml_path IS NULL OR xml_path = '')
          AND EXISTS (
            SELECT 1 FROM sat_cfdi s2
            WHERE UPPER(s2.uuid) = UPPER(sat_cfdi.uuid)
              AND s2.issuer_id = sat_cfdi.issuer_id
              AND s2.direction = sat_cfdi.direction
              AND s2.xml_path IS NOT NULL
          )
    """)

    # Eliminar duplicados: conservar la fila con total (o con más datos)
    dupes = conn.execute("""
        SELECT MIN(uuid), issuer_id, direction FROM sat_cfdi
        GROUP BY UPPER(uuid), issuer_id, direction
        HAVING COUNT(*) > 1
    """).fetchall()

    for (uuid, issuer_id, direction) in dupes:
        rows = conn.execute("""
            SELECT id FROM sat_cfdi
            WHERE issuer_id = ? AND direction = ? AND UPPER(uuid) = UPPER(?)
            ORDER BY (total IS NOT NULL) DESC, (xml_path IS NOT NULL) DESC, id ASC
        """, (issuer_id, direction, uuid)).fetchall()
        keep_id = rows[0][0]
        for r in rows[1:]:
            conn.execute("DELETE FROM sat_cfdi WHERE id = ?", (r[0],))

    conn.commit()
    conn.close()
    print(f"✅ Migración 005 OK (merge duplicados) en DB: {DB_PATH}")

if __name__ == "__main__":
    main()
