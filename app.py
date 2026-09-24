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
from nucleo.catalogo import CATEGORIAS
from nucleo.lista import MAXIMO_ITEMS, parsear_linea
from nucleo.modelos import CotizacionCadena, ItemLista, Oferta, Promo, Veredicto
from nucleo.texto import formatear_envase, pesos
from precios import registro, zonas
from precios.registro import CADENAS
from precios.base import nueva_sesion
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
    initial_sidebar_state="collapsed",
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
) -> tuple[dict[tuple[str, int], list[Oferta]], dict[str, str]]:
    """Trae los candidatos crudos de las cadenas.

    Se cachea solo la parte que sale a la red. Elegir el producto de cada cadena
    es un calculo local y barato que se rehace en cada pasada, y es lo que
    permite que cambiar el envase con el que se compara no vuelva a consultar
    los cinco sitios.
    """
    # La zona no se elige: se consulta siempre la de CABA. Deja de ser una
    # pregunta al usuario, que no aportaba casi nada al precio, pero se sigue
    # usando internamente porque evita que a Coto se le cuele el precio de una
    # sucursal del interior. Ver `precios/zonas.py`.
    return buscar(
        list(items), list(cadenas), zona=zonas.zona_de(zonas.ZONA_POR_DEFECTO)
    )


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


def pantalla_lista(promos: list[Promo]) -> None:
    """Primera pantalla: elegir los productos, como en una gondola.

    Todo lo que hay que decidir antes de comparar se decide aca: que productos,
    en que cadenas y con que se paga. Antes estaba repartido en una barra
    lateral y habia que escribir la lista a mano, que obliga a saber de memoria
    que se quiere comprar y como se escribe.
    """
    st.markdown(
        '<div class="hero"><h1>Arma tu lista</h1>'
        "<p>Elegi lo que necesitas y compara el total en Carrefour, Coto, Jumbo, "
        "Dia y ChangoMas, con las promociones bancarias de cada una.</p></div>",
        unsafe_allow_html=True,
    )
    st.markdown("")

    columna_menu, columna_lista = st.columns([2.3, 1], gap="large")

    with columna_menu:
        pestanas = st.tabs(
            [f"{categoria.icono} {categoria.nombre}" for categoria in CATEGORIAS]
        )
        for pestana, categoria in zip(pestanas, CATEGORIAS):
            with pestana:
                _grilla_de_productos(categoria)

    with columna_lista:
        _panel_de_lista(promos)


def seleccion_actual() -> dict[str, int]:
    """Los productos elegidos y en que cantidad, en el orden en que se agregaron."""
    return st.session_state.setdefault("seleccion", {})


def _grilla_de_productos(categoria) -> None:
    """Los productos de una categoria, como botones que se prenden y apagan."""
    seleccion = seleccion_actual()
    columnas = st.columns(3)
    for indice, producto in enumerate(categoria.productos):
        elegido = producto in seleccion
        with columnas[indice % 3]:
            etiqueta = categoria.etiqueta_de(producto)
            if st.button(
                f"✓ {etiqueta}" if elegido else etiqueta,
                key=f"producto_{categoria.clave}_{indice}",
                type="primary" if elegido else "secondary",
                width="stretch",
            ):
                if elegido:
                    seleccion.pop(producto, None)
                elif len(seleccion) < MAXIMO_ITEMS:
                    seleccion[producto] = 1
                st.rerun()


def _panel_de_lista(promos: list[Promo]) -> None:
    """La lista armada hasta ahora, con las opciones y el boton de comparar."""
    seleccion = seleccion_actual()

    st.markdown(
        f'<div class="panel-lista"><h3>Tu lista</h3>'
        f'<div class="nota">{len(seleccion)} producto'
        f'{"s" if len(seleccion) != 1 else ""}</div></div>',
        unsafe_allow_html=True,
    )
    st.markdown("")

    if not seleccion:
        st.markdown(
            '<div class="vacio">Todavia no elegiste nada.<br>Tocá los productos '
            "del menu para agregarlos.</div>",
            unsafe_allow_html=True,
        )
    for producto in list(seleccion):
        fila = st.columns([3, 2, 1], vertical_alignment="center")
        fila[0].markdown(
            f'<div style="padding-top:.35rem">{producto[:1].upper()}{producto[1:]}</div>',
            unsafe_allow_html=True,
        )
        cantidad = fila[1].number_input(
            "Cantidad",
            min_value=1,
            max_value=20,
            value=seleccion[producto],
            step=1,
            key=f"cantidad_{producto}",
            label_visibility="collapsed",
        )
        seleccion[producto] = int(cantidad)
        if fila[2].button("✕", key=f"quitar_{producto}", help="Quitar de la lista"):
            seleccion.pop(producto, None)
            st.rerun()

    agregado = st.text_input(
        "Agregar algo que no este en el menu",
        placeholder="ej: pan de centeno",
        key="agregado_a_mano",
    )
    if agregado and agregado.strip():
        texto = agregado.strip().lower()
        if texto not in seleccion and len(seleccion) < MAXIMO_ITEMS:
            seleccion[texto] = 1
            st.session_state["agregado_a_mano"] = ""
            st.rerun()

    if len(seleccion) >= MAXIMO_ITEMS:
        st.caption(f"Llegaste al maximo de {MAXIMO_ITEMS} productos.")

    with st.expander("Donde y como pagas"):
        _opciones_de_compra(promos)

    st.markdown("")
    if st.button(
        "Comparar precios",
        type="primary",
        width="stretch",
        disabled=not seleccion,
    ):
        _ir_a_resultados(seleccion)

    if seleccion and st.button("Vaciar lista", width="stretch"):
        st.session_state["seleccion"] = {}
        st.rerun()


def _opciones_de_compra(promos: list[Promo]) -> None:
    """Cadenas, modalidad y medios de pago. Viven dentro del armado de la lista."""
    st.multiselect(
        "Cadenas a comparar",
        options=list(CADENAS),
        default=st.session_state.get("cadenas", list(CADENAS)),
        format_func=lambda clave: CADENAS[clave].nombre,
        key="cadenas",
    )
    st.radio(
        "Como vas a comprar",
        options=["sucursal", "online"],
        horizontal=True,
        format_func=lambda v: "En sucursal" if v == "sucursal" else "Por la web",
        key="modalidad",
        help="Hay promociones que valen solo en el local y otras solo online.",
    )
    st.multiselect(
        "Tus bancos y billeteras",
        options=_entidades_de(promos),
        format_func=nombre_entidad,
        key="entidades",
        help="Solo se aplican las promociones de lo que elijas aca.",
    )
    st.checkbox(
        "Incluir promos sin banco identificado",
        key="incluir_sin_banco",
        help=(
            "Algunas promos no nombran al banco en un campo legible: son de la "
            "tarjeta propia de la cadena o tienen el texto armado a mano. "
            "Activalo para verlas, sabiendo que quiza no te apliquen."
        ),
    )


def _ir_a_resultados(seleccion: dict[str, int]) -> None:
    """Congela la lista elegida y pasa a la comparacion."""
    items = [
        item
        for item in (
            parsear_linea(f"{cantidad}x {texto}")
            for texto, cantidad in seleccion.items()
        )
        if item
    ]
    if not items:
        return
    # Cambiar la lista invalida los envases y marcas fijados a mano: los indices
    # ya no apuntan al mismo producto.
    for clave in [
        k for k in st.session_state if k.startswith(("formato_", "marca_"))
    ]:
        del st.session_state[clave]
    st.session_state["items_activos"] = items
    st.session_state["cadenas_activas"] = st.session_state.get(
        "cadenas", list(CADENAS)
    )
    st.session_state["paso"] = "resultados"
    st.rerun()


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
                            "Producto": (
                                "lo vende, pero sin stock en tu zona"
                                if linea.motivo == "sin_stock"
                                else "no encontrado"
                            ),
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


def pantalla_resultados(promos: list[Promo], fallos: dict[str, str]) -> None:
    """Segunda pantalla: la comparacion de la lista ya armada."""
    encabezado = st.columns([1, 4], vertical_alignment="center")
    if encabezado[0].button("← Editar lista", width="stretch"):
        st.session_state["paso"] = "lista"
        st.rerun()

    items_activos: list[ItemLista] = st.session_state.get("items_activos") or []
    cadenas_activas: list[str] = st.session_state.get("cadenas_activas") or []
    if not items_activos or not cadenas_activas:
        st.session_state["paso"] = "lista"
        st.rerun()
        return

    encabezado[1].markdown(
        f'<div class="nota" style="padding-top:.4rem">Comparando '
        f"{len(items_activos)} productos en {len(cadenas_activas)} cadenas.</div>",
        unsafe_allow_html=True,
    )

    if fallos:
        detalle = ", ".join(
            f"{CADENAS[c].nombre}: {m}" for c, m in fallos.items() if c in CADENAS
        )
        st.warning(
            f"No se pudieron leer las promociones de {len(fallos)} cadena(s). Los "
            "precios siguen siendo correctos, pero a esas cadenas no se les aplica "
            f"descuento. ({detalle})"
        )

    with st.spinner(
        f"Buscando {len(items_activos)} productos en {len(cadenas_activas)} cadenas..."
    ):
        candidatos, errores = buscar_cacheado(
            tuple(items_activos), tuple(cadenas_activas)
        )

    resultado = Resultado(
        items=list(items_activos),
        cadenas=list(cadenas_activas),
        candidatos=candidatos,
        errores=errores,
    )
    fijadas = marcas_elegidas(resultado)
    armar(resultado, formatos_elegidos(resultado, fijadas), fijadas)

    preferencias = Preferencias(
        entidades=frozenset(st.session_state.get("entidades") or ()),
        modalidad=st.session_state.get("modalidad", "sucursal"),
        incluir_sin_banco=bool(st.session_state.get("incluir_sin_banco")),
    )

    hoy = dt.date.today()
    veredictos = evaluar(
        resultado.cotizaciones, promos, dia=hoy, preferencias=preferencias
    )

    if not preferencias.entidades:
        st.info(
            "Volve a la lista y agrega tus bancos o billeteras en **Donde y como "
            "pagas**: la comparacion va a incluir los descuentos que te correspondan."
        )

    tema.titulo("Donde comprar hoy", f"{DIAS_SEMANA[hoy.weekday()]} {hoy:%d/%m}")
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
        mostrar_promociones(promos, cadenas_activas, preferencias, hoy)


def main() -> None:
    """Dos pantallas: primero se arma la lista, despues se compara.

    Separarlas es lo que hace que la app se parezca a comprar y no a llenar un
    formulario: primero elegis, despues ves cuanto sale y donde.
    """
    with st.spinner("Leyendo las promociones de las cinco cadenas..."):
        promos, fallos = cargar_promociones()

    if st.session_state.get("paso") == "resultados":
        pantalla_resultados(promos, fallos)
    else:
        pantalla_lista(promos)


if __name__ == "__main__":
    main()
