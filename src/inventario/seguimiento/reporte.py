"""Reporte HTML del seguimiento del desempeño (una página autocontenida, sin dependencias)."""

from html import escape

import pandas as pd

ESTILO = """
:root { --fondo:#fafaf8; --texto:#1c1c1a; --tenue:#5f5e58; --borde:#dddcd5; --bien:#2f7a3e; --mal:#b3412e; }
@media (prefers-color-scheme: dark) {
  :root { --fondo:#1b1b19; --texto:#ecebe6; --tenue:#a5a49c; --borde:#3a3a36; --bien:#6cc07c; --mal:#ec8a74; }
}
body { background:var(--fondo); color:var(--texto); font:15px/1.5 system-ui, sans-serif; margin:0 auto;
       max-width:1100px; padding:24px 16px; }
h1 { font-size:22px; margin:0 0 4px; } h2 { font-size:17px; margin:32px 0 8px; }
p { color:var(--tenue); margin:4px 0 12px; }
.tabla { overflow-x:auto; }
table { border-collapse:collapse; width:100%; font-variant-numeric:tabular-nums; }
th, td { border-bottom:1px solid var(--borde); padding:6px 10px; text-align:right; white-space:nowrap; }
th:first-child, td:first-child, th.txt, td.txt { text-align:left; }
th { color:var(--tenue); font-weight:600; }
.bien { color:var(--bien); } .mal { color:var(--mal); }
"""

COLUMNAS = {
    "motivo": "Motivo", "ultima_venta_disponible": "Última venta disponible",
    "corte": "Corte", "semana": "Semana", "grupo": "Grupo", "modelo": "Modelo", "cobertura": "Cobertura",
    "dias_observados": "Días con venta", "wape": "WAPE", "sesgo": "Sesgo", "rmsle": "RMSLE",
    "cobertura_p10_p90": "Cobertura P10–P90", "costo_negocio": "Costo diario",
    "unidades_pedidas": "Pedido", "unidades_vendidas": "Venta real", "nivel_servicio": "Servicio",
    "objetivo_servicio": "Objetivo", "faltante": "Faltante", "sobrante": "Sobrante",
    "costo_pedido": "Costo pedido", "costo_referencia": "Costo referencia",
    "ahorro_vs_referencia": "Ahorro vs referencia",
}
PORCENTAJES = {"wape", "sesgo", "cobertura_p10_p90", "nivel_servicio", "objetivo_servicio", "ahorro_vs_referencia"}
TEXTO = {"corte", "semana", "grupo", "modelo", "cobertura", "motivo", "ultima_venta_disponible"}


def _celda(col: str, valor) -> str:
    if col == "corte":
        return f'<td class="txt">{pd.Timestamp(valor):%Y-%m-%d}</td>'
    if col in TEXTO:
        return f'<td class="txt">{escape(str(valor))}</td>'
    if col in PORCENTAJES:
        clase = ""
        if col == "ahorro_vs_referencia":
            clase = ' class="bien"' if valor > 0 else ' class="mal"'
        return f"<td{clase}>{valor:.1%}</td>"
    if col in {"dias_observados"}:
        return f"<td>{int(valor)}</td>"
    if col == "rmsle":
        return f"<td>{valor:.3f}</td>"
    return f"<td>{valor:,.0f}</td>"


def _tabla(df: pd.DataFrame, columnas: list[str]) -> str:
    if df.empty:
        return "<p>Todavía no hay datos.</p>"
    columnas = [c for c in columnas if c in df.columns]
    cab = "".join(f'<th class="{"txt" if c in TEXTO else ""}">{COLUMNAS[c]}</th>' for c in columnas)
    filas = "".join("<tr>" + "".join(_celda(c, f[c]) for c in columnas) + "</tr>" for _, f in df.iterrows())
    return f'<div class="tabla"><table><thead><tr>{cab}</tr></thead><tbody>{filas}</tbody></table></div>'


def html(fecha: pd.Timestamp, por_corte: pd.DataFrame, por_semana: pd.DataFrame,
         por_pedido: pd.DataFrame, correcciones: int, omitidos: pd.DataFrame | None = None) -> str:
    omitidos = omitidos if omitidos is not None else pd.DataFrame()
    seccion_omitidos = ""
    if len(omitidos):
        seccion_omitidos = ("<h2>Cortes sin publicación</h2><p>No se publicó pronóstico ni pedido porque las "
                            "ventas estaban demasiado atrasadas al corte.</p>"
                            + _tabla(omitidos, ["corte", "motivo", "ultima_venta_disponible"]))
    total = por_pedido[por_pedido["grupo"] == "total"] if len(por_pedido) else por_pedido
    resumen = ""
    if len(total):
        ahorro = 1 - total["costo_pedido"].sum() / total["costo_referencia"].sum()
        resumen = (f"<p>{len(total)} pedidos con la semana completa observada. Costo total del pedido "
                   f"sugerido: {total['costo_pedido'].sum():,.0f}; con la regla de referencia (pedir lo "
                   f"vendido la semana anterior): {total['costo_referencia'].sum():,.0f} "
                   f"(<b>{ahorro:.1%}</b> de ahorro).</p>")
    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Seguimiento del desempeño</title><style>{ESTILO}</style></head><body>
<h1>Seguimiento del desempeño</h1>
<p>Datos conocidos al {fecha:%Y-%m-%d}. Las ventas reales incluyen las {correcciones} correcciones que
llegaron hasta esa fecha. Cada corte se evalúa solo en los días cuya venta ya se conoce.</p>
{seccion_omitidos}
<h2>Pedido sugerido</h2>
<p>Solo cortes cuya semana de cobertura ya terminó. Servicio: proporción de tiendas y familias en que
la venta de la semana no superó lo pedido; el objetivo es la proporción crítica de los costos.</p>
{resumen}
{_tabla(por_pedido, ["corte", "grupo", "cobertura", "unidades_pedidas", "unidades_vendidas", "nivel_servicio",
                      "objetivo_servicio", "faltante", "sobrante", "costo_pedido", "costo_referencia",
                      "ahorro_vs_referencia"])}

<h2>Pronóstico por corte</h2>
{_tabla(por_corte, ["corte", "modelo", "dias_observados", "wape", "sesgo", "rmsle", "cobertura_p10_p90",
                    "costo_negocio"])}

<h2>Pronóstico por semana del horizonte</h2>
{_tabla(por_semana, ["corte", "semana", "dias_observados", "wape", "sesgo", "cobertura_p10_p90",
                     "costo_negocio"])}
</body></html>
"""
