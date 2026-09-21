"""Colores y estilos de la aplicacion.

Responsabilidad unica: centralizar la paleta y el CSS. Los mismos valores estan
replicados en `.streamlit/config.toml`, que es lo unico que Streamlit lee para
pintar sus widgets nativos; si cambias uno, cambia el otro.
"""

from __future__ import annotations

import streamlit as st

FONDO = "#0C1117"
PANEL = "#151B24"
BORDE = "#242C3D"
TEXTO = "#E6EDF3"
TENUE = "#8B949E"

VERDE = "#22C55E"  # la opcion mas conveniente
AMBAR = "#F59E0B"  # advertencias y datos parciales
ROJO = "#EF4444"   # errores y faltantes
AZUL = "#38BDF8"   # informacion neutra

# Color identificatorio de cada cadena, tomado de su marca.
COLOR_CADENA = {
    "carrefour": "#0050AA",
    "coto": "#E20025",
    "jumbo": "#00A03C",
    "dia": "#D52B1E",
    "changomas": "#F5A623",
}

_CSS = f"""
<style>
  .bloque-titulo {{
      display: flex; align-items: baseline; gap: .6rem;
      border-bottom: 1px solid {BORDE}; padding-bottom: .4rem; margin: .2rem 0 1rem;
  }}
  .bloque-titulo h2 {{ margin: 0; font-size: 1.15rem; letter-spacing: .01em; }}
  .bloque-titulo span {{ color: {TENUE}; font-size: .85rem; }}

  .tarjeta {{
      background: {PANEL}; border: 1px solid {BORDE}; border-radius: .7rem;
      padding: .9rem 1.1rem; margin-bottom: .6rem;
  }}
  .tarjeta-ganadora {{ border-color: {VERDE}; box-shadow: inset 3px 0 0 {VERDE}; }}

  .fila-cadena {{ display: flex; align-items: center; justify-content: space-between; gap: 1rem; }}
  .nombre-cadena {{ font-weight: 650; font-size: 1.05rem; display: flex; align-items: center; gap: .5rem; }}
  .punto {{ width: .6rem; height: .6rem; border-radius: 50%; display: inline-block; }}

  .monto {{ font-variant-numeric: tabular-nums; font-size: 1.25rem; font-weight: 650; }}
  .monto-tachado {{ color: {TENUE}; text-decoration: line-through; font-size: .9rem; font-weight: 400; }}
  .ahorro {{ color: {VERDE}; font-size: .85rem; }}

  .etiqueta {{
      display: inline-block; padding: .12rem .5rem; border-radius: .4rem;
      font-size: .74rem; border: 1px solid {BORDE}; color: {TENUE};
  }}
  .etiqueta-promo {{ border-color: {VERDE}; color: {VERDE}; }}
  .etiqueta-alerta {{ border-color: {AMBAR}; color: {AMBAR}; }}

  .nota {{ color: {TENUE}; font-size: .82rem; line-height: 1.45; }}

  .dia-calendario {{
      background: {PANEL}; border: 1px solid {BORDE}; border-radius: .6rem;
      padding: .6rem .7rem; height: 100%;
  }}
  .dia-calendario.hoy {{ border-color: {VERDE}; }}
  .dia-nombre {{ color: {TENUE}; font-size: .75rem; text-transform: uppercase; letter-spacing: .04em; }}
</style>
"""


def aplicar() -> None:
    """Inyecta el CSS de la app. Se llama una vez, al arrancar."""
    st.markdown(_CSS, unsafe_allow_html=True)


def titulo(texto: str, aclaracion: str = "") -> None:
    """Encabezado de seccion con una aclaracion opcional al costado."""
    extra = f"<span>{aclaracion}</span>" if aclaracion else ""
    st.markdown(
        f'<div class="bloque-titulo"><h2>{texto}</h2>{extra}</div>', unsafe_allow_html=True
    )


def color_de(cadena: str) -> str:
    return COLOR_CADENA.get(cadena, AZUL)
