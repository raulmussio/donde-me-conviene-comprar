"""Comparador de precios de supermercado y promociones bancarias.

Punto de entrada de la aplicacion Streamlit. Aca vive solo la interfaz: armar
los controles, disparar las consultas y presentar el resultado. Toda la logica
esta en `nucleo`, `precios`, `promociones` y `motor`.

Para correrla:

    streamlit run app.py
"""

from __future__ import annotations

import datetime as dt
import logging

import pandas as pd
import streamlit as st

from motor.canasta import cotizar
from motor.decision import Preferencias, calendario, evaluar, tiene_medio
from nucleo.lista import MAXIMO_ITEMS, parsear_lista
from nucleo.modelos import CotizacionCadena, ItemLista, Promo, Veredicto
from nucleo.texto import formatear_envase, pesos
from precios.registro import CADENAS
from promociones.agregador import obtener_todas
from promociones.bancos import nombre_entidad
from ui import tema

logging.basicConfig(level=logging.WARNING)

DIAS_SEMANA = (
    "Lunes",
    "Martes",
    "Miercoles",
    "Jueves",
    "Viernes",
    "Sabado",
    "Domingo",
)

LISTA_EJEMPLO = """leche entera 1l
2x yerba mate 1kg
aceite girasol 900ml
arroz largo fino 1kg
fideos tirabuzon 500g
azucar 1kg
cafe molido 250g"""

# Cuanto se reusan los datos antes de volver a pedirlos.
TTL_PROMOS = 60 * 60  # las promos bancarias son semanales; una hora sobra
TTL_PRECIOS = 15 * 60  # los precios si se mueven durante el dia


st.set_page_config(
    page_title="Donde me conviene comprar",
    page_icon="$",
    layout="wide",
    initial_sidebar_state="expanded",
)
tema.aplicar()


# ---------------------------------------------------------------------------
# Capa cacheada
# ---------------------------------------------------------------------------


@st.cache_data(ttl=TTL_PROMOS, show_spinner=False)
def cargar_promociones() -> tuple[list[Promo], dict[str, str]]:
    """Promociones de las cinco cadenas, con el detalle de las fuentes caidas."""
    resultado = obtener_todas()
    return resultado.items, resultado.fallos


@st.cache_data(ttl=TTL_PRECIOS, show_spinner=False)
def cotizar_cacheado(
    items: tuple[ItemLista, ...],
    cadenas: tuple[str, ...],
    sucursal_coto: str | None,
) -> dict[str, CotizacionCadena]:
    """Cotiza la lista. Cacheado para que cambiar de banco no rebusque precios."""
    return cotizar(list(items), list(cadenas), sucursal_coto=sucursal_coto)


# ---------------------------------------------------------------------------
# Barra lateral
# ---------------------------------------------------------------------------


def barra_lateral(promos: list[Promo]) -> dict:
    """Dibuja los controles y devuelve lo elegido."""
    with st.sidebar:
        st.markdown("### Tu lista")
        texto = st.text_area(
            "Un producto por linea",
            value=LISTA_EJEMPLO,
            height=210,
            key="lista",
            help=(
                "Escribi cantidad y tamano si te importan: '2x leche 1L' busca "
                "dos litros. Sin tamano, compara cualquier envase."
            ),
        )

        st.markdown("### Donde")
        cadenas = st.multiselect(
            "Cadenas a comparar",
            options=list(CADENAS),
            default=list(CADENAS),
            format_func=lambda clave: CADENAS[clave].nombre,
        )
        modalidad = st.radio(
            "Como vas a comprar",
            options=["sucursal", "online"],
            index=0,
            horizontal=True,
            format_func=lambda v: "En sucursal" if v == "sucursal" else "Por la web",
            help="Hay promociones que valen solo en el local y otras solo online.",
        )

        st.markdown("### Con que pagas")
        entidades = st.multiselect(
            "Tus bancos y billeteras",
            options=_entidades_de(promos),
            default=[],
            format_func=nombre_entidad,
            key="entidades",
            help="Solo se aplican las promociones de lo que elijas aca.",
        )
        incluir_sin_banco = st.checkbox(
            "Incluir promos sin banco identificado",
            value=False,
            help=(
                "Algunas promos no nombran al banco en un campo legible: son de "
                "la tarjeta propia de la cadena o tienen el texto armado a mano. "
                "Activalo para verlas, sabiendo que quiza no te apliquen."
            ),
        )

        st.markdown("---")
        comparar = st.button(
            "Comparar precios", type="primary", width="stretch"
        )
        if st.button("Actualizar promociones", width="stretch"):
            cargar_promociones.clear()
            st.rerun()

    return {
        "texto": texto,
        "cadenas": cadenas,
        "modalidad": modalidad,
        "entidades": entidades,
        "incluir_sin_banco": incluir_sin_banco,
        "comparar": comparar,
    }


def _entidades_de(promos: list[Promo]) -> list[str]:
    """Entidades que aparecen en alguna promo, de la mas frecuente a la menos."""
    conteo: dict[str, int] = {}
    for promo in promos:
        for clave in promo.bancos:
            conteo[clave] = conteo.get(clave, 0) + 1
    return sorted(conteo, key=lambda clave: (-conteo[clave], nombre_entidad(clave)))


# ---------------------------------------------------------------------------
# Presentacion
# ---------------------------------------------------------------------------


def mostrar_ranking(veredictos: list[Veredicto], total_items: int) -> None:
    """Las cadenas ordenadas de mas a menos conveniente para hoy."""
    if not veredictos:
        st.warning("Ninguna cadena pudo cotizar la lista.")
        return

    ganador = veredictos[0]
    peor = max(veredictos, key=lambda v: v.total_final)
    diferencia = peor.total_final - ganador.total_final

    columnas = st.columns(3)
    columnas[0].metric(
        "Te conviene", ganador.nombre, help="Cadena con el total final mas bajo."
    )
    columnas[1].metric("Vas a pagar", pesos(ganador.total_final))
    columnas[2].metric(
        "Contra la mas cara",
        pesos(diferencia),
        delta=f"-{diferencia / peor.total_final:.0%}" if peor.total_final else None,
        delta_color="inverse",
        help=f"Diferencia contra {peor.nombre}, la opcion mas cara de la comparacion.",
    )

    st.markdown("")
    for posicion, veredicto in enumerate(veredictos):
        _tarjeta_cadena(veredicto, es_ganador=posicion == 0, total_items=total_items)


def _tarjeta_cadena(
    veredicto: Veredicto, *, es_ganador: bool, total_items: int
) -> None:
    cotizacion = veredicto.cotizacion
    clase = "tarjeta tarjeta-ganadora" if es_ganador else "tarjeta"
    color = tema.color_de(veredicto.cadena)

    if veredicto.promo:
        importe = (
            f'<span class="monto-tachado">{pesos(veredicto.total_bruto)}</span> '
            f'<span class="monto">{pesos(veredicto.total_final)}</span>'
        )
        detalle = (
            f'<div class="ahorro">Ahorras {pesos(veredicto.ahorro)} &middot; '
            f"{_texto_promo(veredicto.promo)}</div>"
        )
    else:
        importe = f'<span class="monto">{pesos(veredicto.total_final)}</span>'
        detalle = (
            '<div class="nota">Sin promocion aplicable con los medios de pago '
            "elegidos.</div>"
        )

    etiquetas: list[str] = []
    if cotizacion.encontrados < total_items:
        faltan = total_items - cotizacion.encontrados
        etiquetas.append(
            f'<span class="etiqueta etiqueta-alerta">faltan {faltan} de '
            f"{total_items}</span>"
        )
    if cotizacion.error:
        etiquetas.append(
            f'<span class="etiqueta etiqueta-alerta">{cotizacion.error}</span>'
        )

    st.markdown(
        f'<div class="{clase}">'
        f'<div class="fila-cadena">'
        f'<div class="nombre-cadena">'
        f'<span class="punto" style="background:{color}"></span>{cotizacion.nombre}'
        f"</div>"
        f'<div style="text-align:right">{importe}</div>'
        f"</div>{detalle}"
        f'<div style="margin-top:.4rem">{" ".join(etiquetas)}</div>'
        f"</div>",
        unsafe_allow_html=True,
    )


def _texto_promo(promo: Promo) -> str:
    """Resumen corto de una promo para mostrar en una linea."""
    partes: list[str] = []
    if promo.porcentaje:
        partes.append(f"{promo.porcentaje:g}%")
    if promo.bancos:
        partes.append(", ".join(nombre_entidad(clave) for clave in promo.bancos))
    if promo.tope:
        partes.append(f"tope {pesos(promo.tope)}")
    return " &middot; ".join(partes) or promo.titulo


def tabla_por_producto(
    items: list[ItemLista], cotizaciones: dict[str, CotizacionCadena]
) -> None:
    """Una fila por producto, una columna por cadena, con el mas barato marcado."""
    claves = list(cotizaciones)
    filas: list[dict] = []
    minimos: list[float | None] = []

    for indice, item in enumerate(items):
        fila: dict[str, object] = {"Producto": item.etiqueta}
        subtotales: list[float] = []
        for clave in claves:
            linea = cotizaciones[clave].lineas[indice]
            if linea.encontrado:
                fila[CADENAS[clave].nombre] = linea.subtotal
                subtotales.append(linea.subtotal)
            else:
                fila[CADENAS[clave].nombre] = None
        minimos.append(min(subtotales) if subtotales else None)
        filas.append(fila)

    tabla = pd.DataFrame(filas)

    def resaltar(columna: pd.Series) -> list[str]:
        if columna.name == "Producto":
            return [""] * len(columna)
        estilos: list[str] = []
        for valor, minimo in zip(columna, minimos):
            es_minimo = (
                pd.notna(valor) and minimo is not None and abs(valor - minimo) < 0.01
            )
            estilos.append(
                f"color: {tema.VERDE}; font-weight: 600" if es_minimo else ""
            )
        return estilos

    formato = {
        CADENAS[clave].nombre: (lambda v: pesos(v) if pd.notna(v) else "-")
        for clave in claves
    }
    st.dataframe(
        tabla.style.apply(resaltar).format(formato),
        width="stretch",
        hide_index=True,
    )
    st.markdown(
        '<div class="nota">En verde, el mas barato de cada fila. Los importes ya '
        "incluyen la cantidad pedida y, si la cadena solo tiene envases mas chicos, "
        "los envases necesarios para cubrirla.</div>",
        unsafe_allow_html=True,
    )

    with st.expander("Ver que producto exacto tomo cada cadena"):
        for indice, item in enumerate(items):
            st.markdown(f"**{item.etiqueta}**")
            detalle: list[dict] = []
            for clave in claves:
                linea = cotizaciones[clave].lineas[indice]
                if not linea.encontrado:
                    detalle.append(
                        {
                            "Cadena": CADENAS[clave].nombre,
                            "Producto": "no encontrado",
                            "Envase": "-",
                            "Precio": "-",
                            "Envases": "-",
                            "Subtotal": "-",
                        }
                    )
                    continue
                oferta = linea.oferta
                detalle.append(
                    {
                        "Cadena": CADENAS[clave].nombre,
                        "Producto": oferta.nombre,
                        "Envase": formatear_envase(oferta.magnitud, oferta.unidad),
                        "Precio": pesos(oferta.precio),
                        "Envases": str(linea.unidades_totales),
                        "Subtotal": pesos(linea.subtotal),
                    }
                )
            st.dataframe(
                pd.DataFrame(detalle), width="stretch", hide_index=True
            )


def mostrar_calendario(agenda: list, hoy: dt.date) -> None:
    """Los proximos siete dias, con la mejor opcion de cada uno."""
    columnas = st.columns(len(agenda))
    con_datos = [dia for dia in agenda if dia.cadena]
    mejor_dia = min(con_datos, key=lambda d: d.total_final) if con_datos else None

    for columna, dia in zip(columnas, agenda):
        with columna:
            clase = "dia-calendario hoy" if dia.fecha == hoy else "dia-calendario"
            if not dia.cadena:
                cuerpo = '<div class="nota">sin datos</div>'
            else:
                promo = (
                    f'<div class="ahorro">-{pesos(dia.ahorro)}</div>'
                    if dia.ahorro
                    else '<div class="nota">sin promo</div>'
                )
                destaque = (
                    f' style="color:{tema.VERDE}"'
                    if mejor_dia and dia.fecha == mejor_dia.fecha
                    else ""
                )
                cuerpo = (
                    f'<div style="font-weight:600;margin:.2rem 0">'
                    f"{dia.nombre_cadena}</div>"
                    f'<div class="monto"{destaque}>{pesos(dia.total_final)}</div>'
                    f"{promo}"
                )
            st.markdown(
                f'<div class="{clase}">'
                f'<div class="dia-nombre">'
                f"{DIAS_SEMANA[dia.fecha.weekday()][:3]} {dia.fecha:%d/%m}</div>"
                f"{cuerpo}</div>",
                unsafe_allow_html=True,
            )

    if mejor_dia and mejor_dia.fecha != hoy:
        hoy_total = next(
            (d.total_final for d in con_datos if d.fecha == hoy), mejor_dia.total_final
        )
        diferencia = hoy_total - mejor_dia.total_final
        if diferencia > 0:
            st.success(
                f"Esperando al {DIAS_SEMANA[mejor_dia.fecha.weekday()].lower()} "
                f"{mejor_dia.fecha:%d/%m} en {mejor_dia.nombre_cadena} pagas "
                f"{pesos(diferencia)} menos que comprando hoy."
            )


def mostrar_promociones(
    promos: list[Promo],
    cadenas: list[str],
    preferencias: Preferencias,
    hoy: dt.date,
) -> None:
    """Listado de promociones vigentes, con las de hoy primero."""
    filas: list[dict] = []
    for clave in cadenas:
        for promo in promos:
            if promo.cadena != clave or not _pasa_filtro(promo, preferencias):
                continue
            if promo.porcentaje:
                descuento = f"{promo.porcentaje:g}%"
            elif promo.cuotas:
                descuento = f"{promo.cuotas} cuotas"
            else:
                descuento = "-"
            filas.append(
                {
                    "Cadena": CADENAS[clave].nombre,
                    "Hoy": "si" if promo.vigente_el(hoy) else "",
                    "Dias": ", ".join(DIAS_SEMANA[d][:3] for d in sorted(promo.dias)),
                    "Descuento": descuento,
                    "Tope": pesos(promo.tope) if promo.tope else "sin tope",
                    "Entidad": ", ".join(nombre_entidad(b) for b in promo.bancos)
                    or "-",
                    "Promocion": promo.titulo,
                }
            )

    if not filas:
        st.info(
            "No hay promociones que coincidan con los medios de pago elegidos. "
            "Proba agregando bancos en la barra lateral."
        )
        return

    tabla = pd.DataFrame(filas).sort_values(
        ["Hoy", "Cadena", "Descuento"], ascending=[False, True, False]
    )
    st.dataframe(tabla, width="stretch", hide_index=True)


def _pasa_filtro(promo: Promo, preferencias: Preferencias) -> bool:
    """Mismo criterio de medios de pago que usa el motor, para no mostrar de mas."""
    if preferencias.modalidad == "sucursal" and promo.solo_online:
        return False
    if preferencias.modalidad == "online" and promo.solo_sucursal:
        return False
    return tiene_medio(promo, preferencias)


# ---------------------------------------------------------------------------
# Programa principal
# ---------------------------------------------------------------------------


def main() -> None:
    st.title("Donde me conviene comprar")
    st.markdown(
        '<div class="nota">Compara tu lista en Carrefour, Coto, Jumbo, Dia y '
        "ChangoMas con los precios publicados ahora, y le aplica las promociones "
        "bancarias vigentes de cada cadena.</div>",
        unsafe_allow_html=True,
    )
    st.markdown("")

    with st.spinner("Leyendo las promociones de las cinco cadenas..."):
        promos, fallos = cargar_promociones()

    eleccion = barra_lateral(promos)

    if fallos:
        detalle = ", ".join(
            f"{CADENAS[c].nombre}: {m}" for c, m in fallos.items() if c in CADENAS
        )
        st.warning(
            f"No se pudieron leer las promociones de {len(fallos)} cadena(s). Los "
            "precios siguen siendo correctos, pero a esas cadenas no se les aplica "
            f"descuento. ({detalle})"
        )

    items = parsear_lista(eleccion["texto"])
    if not items:
        st.info("Escribi tu lista de compras en la barra lateral para empezar.")
        return
    if len(items) == MAXIMO_ITEMS:
        st.caption(f"Se comparan los primeros {MAXIMO_ITEMS} productos de la lista.")
    if not eleccion["cadenas"]:
        st.info("Elegi al menos una cadena para comparar.")
        return

    preferencias = Preferencias(
        entidades=frozenset(eleccion["entidades"]),
        modalidad=eleccion["modalidad"],
        incluir_sin_banco=eleccion["incluir_sin_banco"],
    )

    firma = (tuple(items), tuple(eleccion["cadenas"]))
    if eleccion["comparar"] or "cotizaciones" not in st.session_state:
        with st.spinner(
            f"Buscando {len(items)} productos en {len(eleccion['cadenas'])} cadenas..."
        ):
            st.session_state["cotizaciones"] = cotizar_cacheado(
                tuple(items), tuple(eleccion["cadenas"]), None
            )
            st.session_state["firma"] = firma

    cotizaciones = st.session_state["cotizaciones"]
    items_mostrados = list(st.session_state["firma"][0])

    # Si cambio la lista o las cadenas sin apretar el boton, lo que hay en
    # pantalla ya no corresponde: se avisa en vez de mostrar datos viejos.
    if st.session_state.get("firma") != firma:
        st.info(
            "Cambiaste la lista o las cadenas. Apreta **Comparar precios** para "
            "actualizar."
        )

    hoy = dt.date.today()
    veredictos = evaluar(cotizaciones, promos, dia=hoy, preferencias=preferencias)

    if not preferencias.entidades:
        st.info(
            "Agrega tus bancos o billeteras en la barra lateral y la comparacion "
            "va a incluir los descuentos que te correspondan."
        )

    tema.titulo("Donde comprar hoy", f"{DIAS_SEMANA[hoy.weekday()]} {hoy:%d/%m}")
    mostrar_ranking(veredictos, total_items=len(items_mostrados))

    pestanas = st.tabs(
        ["Detalle por producto", "Proximos 7 dias", "Promociones vigentes"]
    )

    with pestanas[0]:
        tabla_por_producto(items_mostrados, cotizaciones)

    with pestanas[1]:
        tema.titulo("Que dia conviene comprar", "con los precios de hoy")
        st.markdown(
            '<div class="nota">Los precios son los de ahora: lo que cambia dia a '
            "dia son las promociones bancarias, que se conocen de antemano.</div>",
            unsafe_allow_html=True,
        )
        st.markdown("")
        mostrar_calendario(
            calendario(cotizaciones, promos, desde=hoy, preferencias=preferencias),
            hoy,
        )

    with pestanas[2]:
        tema.titulo("Promociones vigentes", "filtradas por tus medios de pago")
        mostrar_promociones(promos, eleccion["cadenas"], preferencias, hoy)


if __name__ == "__main__":
    main()
