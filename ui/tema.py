"""Colores y estilos de la aplicacion.

Responsabilidad unica: centralizar la paleta y el CSS. Los mismos valores estan
replicados en `.streamlit/config.toml`, que es lo unico que Streamlit lee para
pintar sus widgets nativos; si cambias uno, cambia el otro.

El tema es claro y de acento calido, como las aplicaciones de pedidos: fondo
gris muy suave, tarjetas blancas con borde fino, mucho aire y un solo color
fuerte para lo accionable. El verde queda reservado para una sola cosa, el
ahorro, para que cuando aparezca signifique algo.

Nota practica: Streamlit no reimporta este modulo al recargar la pagina, asi que
un cambio de aca solo se ve reiniciando el servidor.
"""

from __future__ import annotations

import streamlit as st

FONDO = "#F6F7F9"
PANEL = "#FFFFFF"
BORDE = "#E6E8EC"
TEXTO = "#15181D"
TENUE = "#6C7480"
SUAVE = "#F1F3F6"

NARANJA = "#FF5A1F"  # el color de la marca: lo accionable
VERDE = "#14A44D"  # y solo el ahorro
AMBAR = "#F0A202"  # advertencias y datos parciales
ROJO = "#E03131"  # errores y faltantes
AZUL = "#2F6FED"  # informacion neutra

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
  .block-container {{ padding-top: 2.2rem; max-width: 1180px; }}

  /* ---------- encabezados ---------- */
  .bloque-titulo {{
      display: flex; align-items: baseline; gap: .6rem;
      border-bottom: 1px solid {BORDE}; padding-bottom: .5rem; margin: .2rem 0 1.1rem;
  }}
  .bloque-titulo h2 {{ margin: 0; font-size: 1.15rem; letter-spacing: -.01em; }}
  .bloque-titulo span {{ color: {TENUE}; font-size: .85rem; }}

  .hero h1 {{
      margin: 0 0 .3rem; font-size: 2rem; letter-spacing: -.02em; font-weight: 700;
  }}
  .hero p {{ color: {TENUE}; margin: 0; font-size: 1rem; }}

  /* ---------- pasos ---------- */
  .pasos {{ display: flex; gap: .5rem; margin: 0 0 1.6rem; flex-wrap: wrap; }}
  .paso {{
      display: flex; align-items: center; gap: .45rem;
      padding: .3rem .8rem .3rem .4rem; border-radius: 999px;
      background: {PANEL}; border: 1px solid {BORDE};
      font-size: .82rem; color: {TENUE}; white-space: nowrap;
  }}
  .paso .num {{
      width: 1.35rem; height: 1.35rem; border-radius: 50%;
      background: {SUAVE}; color: {TENUE};
      display: inline-flex; align-items: center; justify-content: center;
      font-size: .74rem; font-weight: 600;
  }}
  .paso.activo {{
      background: {NARANJA}; border-color: {NARANJA}; color: #fff; font-weight: 600;
  }}
  .paso.activo .num {{ background: rgba(255,255,255,.25); color: #fff; }}
  .paso.hecho {{ color: {TEXTO}; border-color: {NARANJA}; }}
  .paso.hecho .num {{ background: {NARANJA}; color: #fff; }}

  /* ---------- tarjetas ---------- */
  .tarjeta {{
      background: {PANEL}; border: 1px solid {BORDE}; border-radius: .9rem;
      padding: 1rem 1.15rem; margin-bottom: .7rem;
      box-shadow: 0 1px 2px rgba(16,24,40,.04);
  }}
  .tarjeta-ganadora {{
      border-color: {VERDE};
      box-shadow: 0 0 0 1px {VERDE}, 0 6px 16px rgba(20,164,77,.12);
  }}

  .fila-cadena {{
      display: flex; align-items: center; justify-content: space-between; gap: 1rem;
  }}
  .nombre-cadena {{
      font-weight: 650; font-size: 1.05rem;
      display: flex; align-items: center; gap: .55rem;
  }}
  .punto {{ width: .62rem; height: .62rem; border-radius: 50%; display: inline-block; }}

  .monto {{
      font-variant-numeric: tabular-nums; font-size: 1.3rem; font-weight: 700;
      letter-spacing: -.01em;
  }}
  .monto-tachado {{
      color: {TENUE}; text-decoration: line-through; font-size: .9rem; font-weight: 400;
  }}
  .ahorro {{ color: {VERDE}; font-size: .85rem; font-weight: 500; }}

  .etiqueta {{
      display: inline-block; padding: .14rem .55rem; border-radius: 999px;
      font-size: .74rem; border: 1px solid {BORDE}; color: {TENUE}; background: {SUAVE};
  }}
  .etiqueta-promo {{ border-color: {VERDE}; color: {VERDE}; background: rgba(20,164,77,.08); }}
  .etiqueta-alerta {{ border-color: {AMBAR}; color: #92600A; background: rgba(240,162,2,.1); }}

  .nota {{ color: {TENUE}; font-size: .85rem; line-height: 1.5; }}

  /* ---------- calendario ---------- */
  .dia-calendario {{
      background: {PANEL}; border: 1px solid {BORDE}; border-radius: .8rem;
      padding: .7rem .75rem; height: 100%;
  }}
  .dia-calendario.hoy {{ border-color: {NARANJA}; box-shadow: 0 0 0 1px {NARANJA}; }}
  .dia-nombre {{
      color: {TENUE}; font-size: .73rem; text-transform: uppercase; letter-spacing: .05em;
  }}

  /* ---------- armado de la lista ---------- */
  .panel-lista {{
      background: {PANEL}; border: 1px solid {BORDE}; border-radius: .9rem;
      padding: .9rem 1rem; box-shadow: 0 1px 2px rgba(16,24,40,.04);
  }}
  .panel-lista h3 {{ margin: 0 0 .15rem; font-size: 1.05rem; }}
  .vacio {{
      border: 1px dashed {BORDE}; border-radius: .8rem; padding: 1.4rem 1rem;
      text-align: center; color: {TENUE}; font-size: .87rem; background: {PANEL};
  }}

  /* Los botones del menu de productos: compactos, del mismo alto y con el
     nombre alineado a la izquierda, como un listado y no como un boton de
     accion. Streamlit envuelve la etiqueta en un div propio que la vuelve a
     centrar, asi que hay que alinear tambien ese contenedor. */
  div[data-testid="stButton"] > button {{
      min-height: 2.4rem; padding: .35rem .7rem; line-height: 1.2;
      justify-content: flex-start; border-radius: .6rem;
  }}
  div[data-testid="stButton"] > button > div {{ width: 100%; justify-content: flex-start; }}
  div[data-testid="stButton"] > button p {{ font-size: .85rem; text-align: left; margin: 0; }}

  /* Los de avanzar y volver si van centrados: son acciones, no items. */
  .navegacion div[data-testid="stButton"] > button,
  .navegacion div[data-testid="stButton"] > button > div {{ justify-content: center; }}
  .navegacion div[data-testid="stButton"] > button p {{ text-align: center; }}
</style>
"""


def aplicar() -> None:
    """Inyecta el CSS de la app. Se llama una vez, al arrancar."""
    st.markdown(_CSS, unsafe_allow_html=True)


def titulo(texto: str, aclaracion: str = "") -> None:
    """Encabezado de seccion con una aclaracion opcional al costado."""
    extra = f"<span>{aclaracion}</span>" if aclaracion else ""
    st.markdown(
        f'<div class="bloque-titulo"><h2>{texto}</h2>{extra}</div>',
        unsafe_allow_html=True,
    )


def color_de(cadena: str) -> str:
    return COLOR_CADENA.get(cadena, AZUL)


def barra_de_pasos(pasos: list[tuple[str, str]], actual: str) -> None:
    """Dibuja en que paso del armado esta el usuario.

    `pasos` es una lista de (clave, etiqueta) en orden. El actual se pinta
    lleno, los ya hechos con el numero tildado y los que faltan en gris.
    """
    claves = [clave for clave, _ in pasos]
    posicion = claves.index(actual) if actual in claves else 0

    piezas = []
    for indice, (_, etiqueta) in enumerate(pasos):
        if indice == posicion:
            clase = "paso activo"
        elif indice < posicion:
            clase = "paso hecho"
        else:
            clase = "paso"
        marca = "✓" if indice < posicion else str(indice + 1)
        piezas.append(
            f'<div class="{clase}"><span class="num">{marca}</span>{etiqueta}</div>'
        )
    st.markdown(f'<div class="pasos">{"".join(piezas)}</div>', unsafe_allow_html=True)
