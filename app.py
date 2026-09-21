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

from motor.canasta import Resultado, armar, buscar
from motor.decision import Preferencias, calendario, evaluar, tiene_medio
from nucleo import formato as formatos
from nucleo import marca as marcas
from nucleo.formato import Formato
from nucleo.lista import MAXIMO_ITEMS, parsear_lista
from nucleo.modelos import CotizacionCadena, ItemLista, Oferta, Promo, Veredicto
from nucleo.texto import formatear_envase, pesos
from precios import zonas
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
def buscar_cacheado(
    items: tuple[ItemLista, ...],
    cadenas: tuple[str, ...],
    zona_clave: str,
) -> tuple[dict[tuple[str, int], list[Oferta]], dict[str, str]]:
    """Trae los candidatos crudos de las cadenas.

    Se cachea solo la parte que sale a la red. Elegir el producto de cada cadena
    es un calculo local y barato que se rehace en cada pasada, y es lo que
    permite que cambiar el envase con el que se compara no vuelva a consultar
    los cinco sitios.
    """
    return buscar(list(items), list(cadenas), zona=zonas.zona_de(zona_clave))


def _etiqueta_marca(opcion: marcas.Marca) -> str:
    """Como se muestra una marca en el selector, con en cuantas cadenas existe."""
    return f"{opcion.etiqueta}  ({len(opcion.cadenas)})"


def marcas_elegidas(resultado: Resultado) -> list[str]:
    """La marca fijada para cada item. Vacia cuando sirve cualquiera."""
    elegidas: list[str] = []
    for indice in range(len(resultado.items)):
        guardada = st.session_state.get(_clave_marca(indice))
        disponibles = {
            _etiqueta_marca(opcion): opcion.clave
            for opcion in resultado.opciones_de_marca(indice)
        }
        elegidas.append(disponibles.get(guardada, marcas.LIBRE))
    return elegidas


def formatos_elegidos(resultado: Resultado, fijadas: list[str]) -> list[Formato]:
    """El envase de cada item: el acordado entre cadenas o el que fijo el usuario.

    Se calcula despues de la marca porque depende de ella: los envases de
    Casancrem no son los de La Paulina, y al cambiar de marca el envase elegido
    antes puede dejar de existir.
    """
    elegidos: list[Formato] = []
    for indice, item in enumerate(resultado.items):
        clave_marca = fijadas[indice] if indice < len(fijadas) else marcas.LIBRE
        opciones = resultado.opciones_de_formato(indice, marca=clave_marca)
        guardado = st.session_state.get(_clave_formato(indice))
        elegido = next((o for o in opciones if o.etiqueta == guardado), None)
        elegidos.append(
            elegido
            or formatos.consensuar(item, resultado.por_cadena(indice, marca=clave_marca))
        )
    return elegidos


def _clave_formato(indice: int) -> str:
    return f"formato_{indice}"


def _clave_marca(indice: int) -> str:
    return f"marca_{indice}"


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
        zona = st.selectbox(
            "Tu zona",
            options=list(zonas.ZONAS),
            index=list(zonas.ZONAS).index(zonas.ZONA_POR_DEFECTO),
            format_func=lambda clave: zonas.ZONAS[clave].nombre,
            help=(
                "Define que lista de precios se consulta. Carrefour y Dia cotizan "
                "igual en toda el area metropolitana; ChangoMas cambia entre CABA "
                "y el oeste y el sur del conurbano. Jumbo no publica precios por "
                "zona: se informa el de su tienda online."
            ),
        )
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
        "zona": zona,
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
    peor = max(veredictos, key=lambda v: v.total_canasta)

    columnas = st.columns(3)
    columnas[0].metric(
        "Te conviene",
        ganador.nombre,
        help=(
            "Cadena con la canasta completa mas barata. Si a una cadena le falta "
            "un producto, se le suma lo que costaria conseguirlo en otro lado, "
            "para que todas se comparen sobre la misma lista."
        ),
    )
    columnas[1].metric(
        "Vas a pagar ahi",
        pesos(ganador.total_final),
        help=(
            f"Mas {pesos(ganador.estimado_afuera)} estimados por los "
            f"{ganador.faltantes} productos que no tiene."
            if ganador.faltantes
            else None
        ),
    )

    # Con una sola cadena no hay contra que comparar, y con un empate la
    # diferencia es cero: mostrar "-0%" en verde seria decir algo que no pasa.
    diferencia = peor.total_canasta - ganador.total_canasta
    if len(veredictos) > 1 and diferencia > 0.01:
        columnas[2].metric(
            "Contra la mas cara",
            pesos(diferencia),
            delta=f"-{diferencia / peor.total_canasta:.0%}",
            delta_color="inverse",
            help=f"Diferencia contra {peor.nombre}, la opcion mas cara.",
        )
    else:
        columnas[2].metric("Cadenas comparadas", str(len(veredictos)))

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

    if veredicto.faltantes:
        importe += (
            f' <span class="nota">+ {pesos(veredicto.estimado_afuera)} afuera '
            f"= <b>{pesos(veredicto.total_canasta)}</b></span>"
        )

    etiquetas: list[str] = []
    # Si la cadena no publica precios por zona, hay que decirlo donde se lee el
    # precio: con "GBA Sur" elegido arriba, nadie supondria que una de las cinco
    # esta mostrando otra cosa.
    if not CADENAS[veredicto.cadena].soporta_zona:
        etiquetas.append(
            '<span class="etiqueta">precio de su tienda online, no por zona</span>'
        )
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


def selectores_por_producto(resultado: Resultado) -> None:
    """Deja fijar a mano la marca y el envase con los que se compara cada producto.

    La app acuerda sola el envase mas comun entre las cinco cadenas y no fija
    ninguna marca, que es lo razonable cuando no sabe que queres. Pero el
    acuerdo puede no ser el tuyo: "coca cola" puede resolverse en 1,75 L cuando
    querias la de 2,25, y "queso crema" puede cotizar la segunda marca de cada
    cadena cuando vos comprabas Casancrem.

    Cambiar cualquiera de los dos no vuelve a consultar los sitios: rehace la
    eleccion sobre los productos que ya se trajeron.
    """
    st.markdown(
        '<div class="nota">La app compara todas las cadenas con el envase que '
        "mas de ellas tienen y sin fijar marca. Si queres una marca puntual o "
        "un envase distinto, elegilos aca. Entre parentesis, en cuantas cadenas "
        "existe cada marca: mientras mas, mas completa la comparacion.</div>",
        unsafe_allow_html=True,
    )
    st.markdown("")

    encabezado = st.columns([3, 4, 3])
    encabezado[0].caption("Producto")
    encabezado[1].caption("Marca")
    encabezado[2].caption("Envase")

    for indice, item in enumerate(resultado.items):
        columnas = st.columns([3, 4, 3])
        columnas[0].markdown(
            f'<div style="padding-top:.55rem">{item.etiqueta}</div>',
            unsafe_allow_html=True,
        )
        with columnas[1]:
            _selector_de_marca(resultado, indice)
        with columnas[2]:
            _selector_de_envase(resultado, indice)


def _selector_de_marca(resultado: Resultado, indice: int) -> None:
    opciones = resultado.opciones_de_marca(indice)
    if not opciones:
        st.caption("sin marcas reconocidas")
        return

    etiquetas = [marcas.ETIQUETA_LIBRE] + [
        _etiqueta_marca(opcion) for opcion in opciones
    ]
    clave = _clave_marca(indice)
    _descartar_si_no_esta(clave, etiquetas)
    st.selectbox(
        "Marca",
        options=etiquetas,
        key=clave,
        label_visibility="collapsed",
    )


def _selector_de_envase(resultado: Resultado, indice: int) -> None:
    opciones = resultado.opciones_de_formato(indice)
    if not opciones:
        st.caption("sin envase reconocido")
        return

    etiquetas = [opcion.etiqueta for opcion in opciones]
    clave = _clave_formato(indice)
    _descartar_si_no_esta(clave, etiquetas)

    actual = resultado.formatos[indice].etiqueta
    if clave not in st.session_state and actual in etiquetas:
        st.session_state[clave] = actual

    st.selectbox(
        "Envase",
        options=etiquetas,
        key=clave,
        label_visibility="collapsed",
    )


def _descartar_si_no_esta(clave: str, etiquetas: list[str]) -> None:
    """Olvida una eleccion que dejo de existir.

    Pasa al cambiar de marca: el envase de 500 g que se habia elegido para
    Casancrem no existe para La Paulina. Streamlit falla si el valor guardado de
    un selector no esta entre sus opciones, asi que se limpia antes de dibujarlo.
    """
    if clave in st.session_state and st.session_state[clave] not in etiquetas:
        del st.session_state[clave]


def _nombre_marca(resultado: Resultado, indice: int, clave: str) -> str:
    """Nombre presentable de una marca fijada, a partir de su clave interna."""
    for opcion in resultado.opciones_de_marca(indice):
        if opcion.clave == clave:
            return opcion.etiqueta
    return clave.title()


def tabla_por_producto(resultado: Resultado) -> None:
    """Una fila por producto, una columna por cadena, con el mas barato marcado."""
    items = resultado.items
    cotizaciones = resultado.cotizaciones
    claves = list(cotizaciones)
    filas: list[dict] = []
    minimos: list[float | None] = []

    for indice, item in enumerate(items):
        etiqueta = item.etiqueta
        aclaraciones: list[str] = []
        marca_fijada = resultado.marca_de(indice)
        if marca_fijada:
            aclaraciones.append(_nombre_marca(resultado, indice, marca_fijada))
        envase = resultado.formatos[indice] if indice < len(resultado.formatos) else None
        if envase and not envase.es_libre:
            aclaraciones.append(envase.etiqueta)
        if aclaraciones:
            etiqueta = f"{etiqueta}  ({', '.join(aclaraciones)})"
        fila: dict[str, object] = {"Producto": etiqueta}
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
            envase = resultado.formatos[indice]
            marca_fijada = resultado.marca_de(indice)
            detalle_marca = (
                f"{_nombre_marca(resultado, indice, marca_fijada)}, "
                if marca_fijada
                else ""
            )
            st.markdown(
                f"**{item.etiqueta}** - comparando {detalle_marca}en {envase.etiqueta}"
            )
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
            st.dataframe(pd.DataFrame(detalle), width="stretch", hide_index=True)


def mostrar_calendario(agenda: list, hoy: dt.date) -> None:
    """Los proximos siete dias, con la mejor opcion de cada uno."""
    columnas = st.columns(len(agenda))
    con_datos = [dia for dia in agenda if dia.cadena]
    mejor_dia = min(con_datos, key=lambda d: d.total_canasta) if con_datos else None

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
                    f'<div class="monto"{destaque}>{pesos(dia.total_canasta)}</div>'
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
            (d.total_canasta for d in con_datos if d.fecha == hoy),
            mejor_dia.total_canasta,
        )
        diferencia = hoy_total - mejor_dia.total_canasta
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

    # La lista que se compara se congela al apretar el boton. Asi editar el
    # texto no dispara consultas a cinco sitios en cada pasada de Streamlit.
    if eleccion["comparar"] or "items_activos" not in st.session_state:
        # Cambiar la lista invalida los envases que el usuario habia fijado a
        # mano: los indices ya no apuntan al mismo producto.
        for clave in [
            k
            for k in st.session_state
            if k.startswith("formato_") or k.startswith("marca_")
        ]:
            del st.session_state[clave]
        st.session_state["items_activos"] = items
        st.session_state["cadenas_activas"] = eleccion["cadenas"]
        st.session_state["zona_activa"] = eleccion["zona"]

    items_activos: list[ItemLista] = st.session_state["items_activos"]
    cadenas_activas: list[str] = st.session_state["cadenas_activas"]
    zona_activa: str = st.session_state["zona_activa"]

    with st.spinner(
        f"Buscando {len(items_activos)} productos en {len(cadenas_activas)} cadenas..."
    ):
        candidatos, errores = buscar_cacheado(
            tuple(items_activos), tuple(cadenas_activas), zona_activa
        )

    resultado = Resultado(
        items=list(items_activos),
        cadenas=list(cadenas_activas),
        candidatos=candidatos,
        errores=errores,
    )
    fijadas = marcas_elegidas(resultado)
    armar(resultado, formatos_elegidos(resultado, fijadas), fijadas)

    # Si cambio la lista o las cadenas sin apretar el boton, lo que hay en
    # pantalla ya no corresponde: se avisa en vez de mostrar datos viejos.
    if (
        items != items_activos
        or eleccion["cadenas"] != cadenas_activas
        or eleccion["zona"] != zona_activa
    ):
        st.info(
            "Cambiaste la lista, las cadenas o la zona. Apreta "
            "**Comparar precios** para actualizar."
        )

    hoy = dt.date.today()
    veredictos = evaluar(
        resultado.cotizaciones, promos, dia=hoy, preferencias=preferencias
    )

    if not preferencias.entidades:
        st.info(
            "Agrega tus bancos o billeteras en la barra lateral y la comparacion "
            "va a incluir los descuentos que te correspondan."
        )

    tema.titulo(
        "Donde comprar hoy",
        f"{DIAS_SEMANA[hoy.weekday()]} {hoy:%d/%m} &middot; "
        f"{zonas.zona_de(zona_activa).nombre}",
    )
    mostrar_ranking(veredictos, total_items=len(items_activos))

    pestanas = st.tabs(
        ["Detalle por producto", "Proximos 7 dias", "Promociones vigentes"]
    )

    with pestanas[0]:
        selectores_por_producto(resultado)
        st.markdown("---")
        tabla_por_producto(resultado)

    with pestanas[1]:
        tema.titulo("Que dia conviene comprar", "con los precios de hoy")
        st.markdown(
            '<div class="nota">Los precios son los de ahora: lo que cambia dia a '
            "dia son las promociones bancarias, que se conocen de antemano.</div>",
            unsafe_allow_html=True,
        )
        st.markdown("")
        mostrar_calendario(
            calendario(
                resultado.cotizaciones, promos, desde=hoy, preferencias=preferencias
            ),
            hoy,
        )

    with pestanas[2]:
        tema.titulo("Promociones vigentes", "filtradas por tus medios de pago")
        mostrar_promociones(promos, eleccion["cadenas"], preferencias, hoy)


if __name__ == "__main__":
    main()
