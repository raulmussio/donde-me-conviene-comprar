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
import streamlit.components.v1 as componentes

from motor.canasta import Resultado, armar, buscar
from motor.decision import Preferencias, calendario, evaluar, tiene_medio
from nucleo import formato as formatos
from nucleo import marca as marcas
from nucleo.formato import Formato
from nucleo.catalogo import CATEGORIA_POR_CLAVE, CATEGORIAS
from nucleo.lista import MAXIMO_ITEMS, parsear_linea
from nucleo.modelos import CotizacionCadena, ItemLista, Oferta, Promo, Veredicto
from nucleo.texto import formatear_envase, normalizar, pesos
from precios import registro, zonas
from precios.registro import CADENAS
from precios.base import nueva_sesion
from promociones.agregador import obtener_todas
from promociones.bancos import nombre_corto, nombre_entidad
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

# Alto en pixeles del marco con scroll donde vive la lista elegida. Fijarlo es
# lo que mantiene el boton de continuar siempre a la vista.
ALTO_DE_LA_LISTA = 420


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


PASOS: list[tuple[str, str]] = [
    ("productos", "Productos"),
    ("cadenas", "Supermercados"),
    ("pago", "Medios de pago"),
    ("ajustes", "Marcas y envases"),
    ("resultados", "Resultados"),
]


def paso_actual() -> str:
    return st.session_state.setdefault("paso", "productos")


def _volver_al_tope() -> None:
    """Sube la pagina cuando se pasa de un paso a otro.

    Streamlit conserva la posicion del scroll entre pasadas, asi que si el boton
    de avanzar estaba al pie de una pantalla larga, la siguiente aparecia
    empezada por el final. El que scrollea no es la ventana sino el contenedor
    `stMain`, y como el script corre dentro de un iframe hay que alcanzarlo por
    `window.parent`.

    Solo se dispara al cambiar de paso: hacerlo en cada pasada devolveria al
    tope cada vez que se toca un selector.

    Usa `components.html` y no `st.html`, que es su reemplazo moderno, porque
    `st.html` inserta el `<script>` en el documento pero no lo ejecuta ni con
    `unsafe_allow_javascript`: el tag queda en el DOM y no pasa nada. El iframe
    de `components.html` si lo corre.
    """
    actual = st.session_state.get("paso", "productos")
    if st.session_state.get("_paso_mostrado") == actual:
        return
    st.session_state["_paso_mostrado"] = actual
    # El token hace que el bloque cambie de contenido y Streamlit vuelva a
    # montarlo; con un HTML identico no volveria a ejecutar el script.
    token = st.session_state.get("_saltos", 0) + 1
    st.session_state["_saltos"] = token
    componentes.html(
        f"""<script>
            const doc = window.parent.document;
            const principal = doc.querySelector('section[data-testid="stMain"]');
            if (principal) principal.scrollTo({{top: 0}});
            doc.documentElement.scrollTop = 0;
            /* {token} */
        </script>""",
        height=0,
    )


def ir_a(paso: str) -> None:
    st.session_state["paso"] = paso
    st.rerun()


def seleccion_actual() -> dict[str, int]:
    """Los productos elegidos y en que cantidad, en el orden en que se agregaron."""
    return st.session_state.setdefault("seleccion", {})


def cadenas_elegidas() -> list[str]:
    return st.session_state.setdefault("cadenas", list(CADENAS))


def _navegacion(
    volver: str | None, avanzar: str | None, etiqueta: str, habilitado: bool = True
) -> None:
    """Los botones de ir y volver, iguales en todos los pasos."""
    st.markdown("")
    st.markdown('<div class="navegacion">', unsafe_allow_html=True)
    columnas = st.columns([1, 1, 2])
    if volver and columnas[0].button("← Volver", width="stretch"):
        ir_a(volver)
    if avanzar and columnas[2].button(
        etiqueta, type="primary", width="stretch", disabled=not habilitado
    ):
        ir_a(avanzar)
    st.markdown("</div>", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Paso 1: los productos
# ---------------------------------------------------------------------------


def paso_productos() -> None:
    """Elegir que se va a comprar, de un menu por categorias."""
    st.markdown(
        '<div class="hero"><h1>¿Qué necesitás comprar?</h1>'
        "<p>Elegí de las categorías y armá tu lista. Después vemos dónde sale "
        "más barata.</p></div>",
        unsafe_allow_html=True,
    )
    tema.barra_de_pasos(PASOS, "productos")

    seleccion = seleccion_actual()

    # El selector va a lo ancho de la pagina y no dentro de la columna del
    # menu: con trece categorias, el ancho de la columna dejaba los nombres
    # cortados en "Perfu..." y "Desay...".
    categoria = _selector_de_categoria()
    st.markdown("")

    columna_menu, columna_lista = st.columns([2.3, 1], gap="large")
    with columna_menu:
        _grilla_de_productos(categoria, seleccion)
    with columna_lista:
        _panel_de_lista(seleccion)

    _barra_flotante(seleccion)


def _selector_de_categoria():
    """El rubro que se esta mirando, en un desplegable.

    Antes eran fichas, y aun acomodandose solas ocupaban seis filas en el
    telefono antes de llegar al primer producto. Un desplegable ocupa una,
    y ademas se lee como lo que es: elegis un rubro, no apretas un boton.
    """
    st.selectbox(
        "Categoría",
        options=[categoria.clave for categoria in CATEGORIAS],
        format_func=_etiqueta_categoria,
        key="categoria_activa",
        # Sin buscador: es una lista cerrada de trece. Con el buscador puesto,
        # en el telefono cada toque abre el teclado y tapa media pantalla.
        filter_mode=None,
    )
    return CATEGORIA_POR_CLAVE.get(
        st.session_state.get("categoria_activa", CATEGORIAS[0].clave), CATEGORIAS[0]
    )


def _etiqueta_categoria(clave: str) -> str:
    """Nombre del rubro para el desplegable.

    No lleva cuantos productos suyos ya elegiste, por mas util que seria: la
    etiqueta tiene que ser **siempre la misma**. Si cambia entre pasadas, el
    desplegable pierde la seleccion y vuelve a la primera categoria. Se veia al
    elegir el segundo producto de un rubro: el primero lo aguantaba y con el
    segundo saltaba de vuelta a Almacen. El contador vive debajo, en el texto
    que dice cuantos productos tiene el rubro.
    """
    categoria = CATEGORIA_POR_CLAVE[clave]
    return f"{categoria.icono}  {categoria.nombre}"


def _grilla_de_productos(categoria, seleccion: dict[str, int]) -> None:
    """Los productos de la categoria abierta, en grilla."""
    # Sin repetir el nombre del rubro, que ya lo dice el desplegable de arriba.
    # Aca si puede ir el contador de elegidos: es texto suelto, no la etiqueta
    # de un widget con estado.
    elegidos = sum(1 for producto in categoria.productos if producto in seleccion)
    detalle = f" &middot; {elegidos} en tu lista" if elegidos else ""
    st.markdown(
        f'<div class="nota" style="margin:.2rem 0 .5rem">'
        f"{len(categoria.productos)} productos{detalle}</div>",
        unsafe_allow_html=True,
    )
    # Un contenedor que envuelve, no columnas: el ancho de cada boton lo fija el
    # CSS, tres por fila en pantalla grande y dos en el telefono. Con columnas,
    # Streamlit las apila en pantalla angosta y quedaba un producto por fila.
    with st.container(horizontal=True, wrap=True, gap="small", key="productos"):
        for indice, producto in enumerate(categoria.productos):
            elegido = producto in seleccion
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


def _panel_de_lista(seleccion: dict[str, int]) -> None:
    """La lista armada hasta ahora, con su cantidad por producto.

    El boton de continuar va arriba y los productos abajo, dentro de un marco
    con scroll propio. Al reves, una lista de treinta y cinco productos empujaba
    el boton tan abajo que habia que recorrer toda la pagina para encontrarlo.
    """
    st.markdown(
        f'<div class="panel-lista"><h3>Tu lista</h3>'
        f'<div class="nota">{len(seleccion)} producto'
        f'{"s" if len(seleccion) != 1 else ""}</div></div>',
        unsafe_allow_html=True,
    )
    st.markdown("")

    with st.container(key="continuar_escritorio"):
        if st.button(
            "Continuar →",
            type="primary",
            width="stretch",
            disabled=not seleccion,
            key="continuar_productos",
        ):
            ir_a("cadenas")

    if not seleccion:
        st.markdown(
            '<div class="vacio">Todavía no elegiste nada.<br>Tocá los productos '
            "del menú para agregarlos.</div>",
            unsafe_allow_html=True,
        )
    else:
        with st.container(height=ALTO_DE_LA_LISTA):
            for producto in list(seleccion):
                fila = st.columns([3, 2, 1], vertical_alignment="center")
                fila[0].markdown(
                    f'<div style="padding-top:.4rem;font-size:.9rem">'
                    f"{producto[:1].upper()}{producto[1:]}</div>",
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
                if fila[2].button(
                    "✕", key=f"quitar_{producto}", help="Quitar de la lista"
                ):
                    seleccion.pop(producto, None)
                    st.rerun()

    agregado = st.text_input(
        "¿No está en el menú?",
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
        st.caption(f"Llegaste al máximo de {MAXIMO_ITEMS} productos.")
    elif seleccion and st.button("Vaciar lista", width="stretch"):
        st.session_state["seleccion"] = {}
        st.rerun()


def _barra_flotante(seleccion: dict[str, int]) -> None:
    """En el telefono, la lista y el boton quedan fijos al pie.

    Hace falta porque en pantalla angosta Streamlit apila las dos columnas: el
    panel con la lista y el boton de continuar terminan debajo de los cuarenta
    productos de la categoria, o sea fuera de la vista. Es el mismo recurso que
    usan las aplicaciones de pedidos con el carrito.
    """
    if not seleccion:
        return
    with st.container(key="barra_movil"):
        if st.button(
            f"Continuar con {len(seleccion)} producto"
            f"{'s' if len(seleccion) != 1 else ''} →",
            type="primary",
            width="stretch",
            key="continuar_movil",
        ):
            ir_a("cadenas")


# ---------------------------------------------------------------------------
# Paso 2: las cadenas
# ---------------------------------------------------------------------------


def paso_cadenas() -> None:
    """Elegir contra que supermercados comparar."""
    st.markdown(
        '<div class="hero"><h1>¿Dónde querés comparar?</h1>'
        "<p>Mientras más cadenas, mejor la comparación. Sacá las que no te "
        "queden cerca.</p></div>",
        unsafe_allow_html=True,
    )
    tema.barra_de_pasos(PASOS, "cadenas")

    elegidas = cadenas_elegidas()

    # Fichas que envuelven, no una columna por cadena: en el telefono Streamlit
    # las apila y quedaban cinco barras de ancho completo, cada una con su punto
    # de color flotando arriba y sin relacion visible con el nombre. El punto
    # ahora va dentro de la ficha, puesto por CSS.
    with st.container(horizontal=True, wrap=True, gap="small", key="cadenas"):
        for clave in CADENAS:
            activa = clave in elegidas
            if st.button(
                CADENAS[clave].nombre,
                key=f"cadena_{clave}",
                type="primary" if activa else "secondary",
                width="content",
            ):
                if activa and len(elegidas) > 1:
                    elegidas.remove(clave)
                elif not activa:
                    elegidas.append(clave)
                st.rerun()

    st.markdown("")
    st.markdown(
        '<div class="nota">Cómo vas a comprar cambia qué promociones aplican: hay '
        "descuentos que valen solo en el local y otros solo por la web.</div>",
        unsafe_allow_html=True,
    )
    st.radio(
        "Cómo vas a comprar",
        options=["sucursal", "online"],
        horizontal=True,
        format_func=lambda v: "En sucursal" if v == "sucursal" else "Por la web",
        key="modalidad",
        label_visibility="collapsed",
    )

    _navegacion("productos", "pago", "Continuar →", habilitado=bool(elegidas))


# ---------------------------------------------------------------------------
# Paso 3: los medios de pago
# ---------------------------------------------------------------------------


def paso_pago(promos: list[Promo]) -> None:
    """Elegir con que se paga, que es lo que habilita los descuentos."""
    st.markdown(
        '<div class="hero"><h1>¿Con qué vas a pagar?</h1>'
        "<p>Elegí tus bancos y billeteras. Solo se aplican los descuentos de lo "
        "que marques acá.</p></div>",
        unsafe_allow_html=True,
    )
    tema.barra_de_pasos(PASOS, "pago")

    elegidas = st.session_state.setdefault("entidades", [])

    # Fichas que envuelven, no cuatro columnas: en el telefono las columnas se
    # apilan y las treinta y seis entidades quedaban una debajo de otra, con la
    # pagina midiendo dos mil seiscientos pixeles de alto.
    with st.container(horizontal=True, wrap=True, gap="small", key="entidades"):
        for clave in _entidades_de(promos):
            activa = clave in elegidas
            nombre = nombre_corto(clave)
            if st.button(
                f"✓ {nombre}" if activa else nombre,
                key=f"entidad_{clave}",
                type="primary" if activa else "secondary",
                width="content",
            ):
                if activa:
                    elegidas.remove(clave)
                else:
                    elegidas.append(clave)
                st.rerun()

    st.markdown("")
    st.checkbox(
        "Incluir promos sin banco identificado",
        key="incluir_sin_banco",
        help=(
            "Algunas promos no nombran al banco en un campo legible: son de la "
            "tarjeta propia de la cadena o tienen el texto armado a mano. "
            "Activalo para verlas, sabiendo que quizá no te apliquen."
        ),
    )
    if not elegidas:
        st.markdown(
            '<div class="nota">Podés seguir sin elegir ninguno, pero entonces la '
            "comparación va a ser solo por precio de lista.</div>",
            unsafe_allow_html=True,
        )

    _navegacion("cadenas", "ajustes", "Buscar precios →")


# ---------------------------------------------------------------------------
# Paso 4: marcas y envases
# ---------------------------------------------------------------------------


def paso_ajustes() -> None:
    """Revisar que marca y que envase se compara, antes de ver los totales."""
    st.markdown(
        '<div class="hero"><h1>¿Alguna marca en particular?</h1>'
        "<p>Ya buscamos tu lista en cada cadena. Así quedó lo que se va a "
        "comparar: cambiá lo que no sea lo que querías.</p></div>",
        unsafe_allow_html=True,
    )
    tema.barra_de_pasos(PASOS, "ajustes")

    resultado = _resultado_actual()
    if resultado is None:
        return

    selectores_por_producto(resultado)
    _navegacion("pago", "resultados", "Ver comparación →")


def _resultado_actual() -> Resultado | None:
    """Busca la lista en las cadenas elegidas y arma la cotizacion.

    Lo usan el paso de marcas y el de resultados. La busqueda esta cacheada, asi
    que ir y volver entre los dos no vuelve a consultar los sitios.
    """
    items = _items_de_la_seleccion()
    cadenas = cadenas_elegidas()
    if not items or not cadenas:
        ir_a("productos")
        return None

    with st.spinner(f"Buscando {len(items)} productos en {len(cadenas)} cadenas..."):
        candidatos, errores = buscar_cacheado(tuple(items), tuple(cadenas))

    resultado = Resultado(
        items=list(items),
        cadenas=list(cadenas),
        candidatos=candidatos,
        errores=errores,
    )
    fijadas = marcas_elegidas(resultado)
    armar(resultado, formatos_elegidos(resultado, fijadas), fijadas)
    return resultado


def _items_de_la_seleccion() -> list[ItemLista]:
    """Convierte lo elegido en el menu a items de lista."""
    return [
        item
        for item in (
            parsear_linea(f"{cantidad}x {texto}")
            for texto, cantidad in seleccion_actual().items()
        )
        if item
    ]


def _entidades_de(promos: list[Promo]) -> list[str]:
    """Entidades que aparecen en alguna promo, en orden alfabetico.

    Antes iban de la mas frecuente a la menos, que sirve para un ranking pero no
    para encontrar la tuya entre treinta y seis. Sin un buscador donde escribir,
    la unica forma de que se pueda buscar con la vista es que el orden sea el
    que uno espera. Se ordena sin acentos para que "Cordoba" caiga donde
    corresponde.
    """
    encontradas = {clave for promo in promos for clave in promo.bancos}
    return sorted(encontradas, key=lambda clave: normalizar(nombre_corto(clave)))


# ---------------------------------------------------------------------------
# Presentacion
# ---------------------------------------------------------------------------


def mostrar_ranking(veredictos: list[Veredicto], total_items: int) -> None:
    """Las cadenas ordenadas de mas a menos conveniente para hoy."""
    if not veredictos:
        st.warning("Ninguna cadena pudo cotizar la lista.")
        return

    ganador = veredictos[0]

    columnas = st.columns(3)
    columnas[0].metric(
        "Te conviene",
        ganador.nombre,
        help=(
            "La mas barata producto por producto. No se compara por el total, "
            "porque el total de una cadena a la que le faltan productos es mas "
            "bajo sin que sea mas barata."
        ),
    )
    columnas[1].metric(
        "Vas a pagar ahí",
        pesos(ganador.total_final),
        help=(
            f"Por los {ganador.cotizacion.encontrados} de {total_items} productos "
            "de tu lista que esta cadena tiene. Lo que falte lo conseguís después."
        ),
    )

    diferencia = ganador.diferencia_porcentual
    if ganador.comparables and abs(diferencia) >= 0.5:
        columnas[2].metric(
            "Contra el precio típico",
            f"{abs(diferencia):.0f}% {'más barata' if diferencia < 0 else 'más cara'}",
            delta=f"{diferencia:+.0f}%",
            delta_color="inverse",
            help=(
                f"Comparando uno por uno los {ganador.comparables} productos que "
                "cotizaron al menos dos cadenas, contra el precio típico de cada "
                "uno."
            ),
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
            f'<div class="ahorro">Ahorrás {pesos(veredicto.ahorro)} &middot; '
            f"{_texto_promo(veredicto.promo)}</div>"
        )
    else:
        importe = f'<span class="monto">{pesos(veredicto.total_final)}</span>'
        detalle = (
            '<div class="nota">Sin promoción aplicable con los medios de pago '
            "elegidos.</div>"
        )

    etiquetas: list[str] = []
    # El indice va primero porque es lo que explica el orden: sin el, una cadena
    # con un total mas alto arriba de otra con uno mas bajo parece un error.
    diferencia = veredicto.diferencia_porcentual
    if veredicto.comparables and abs(diferencia) >= 0.5:
        clase_indice = "etiqueta etiqueta-promo" if diferencia < 0 else "etiqueta"
        texto = (
            f"{abs(diferencia):.0f}% más barata que el promedio"
            if diferencia < 0
            else f"{diferencia:.0f}% más cara que el promedio"
        )
        etiquetas.append(f'<span class="{clase_indice}">{texto}</span>')

    if cotizacion.encontrados < total_items:
        faltan = total_items - cotizacion.encontrados
        etiquetas.append(
            f'<span class="etiqueta etiqueta-alerta">no tiene {faltan} de '
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
        filter_mode=None,
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
        filter_mode=None,
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
    mejor_dia = min(con_datos, key=lambda d: d.indice) if con_datos else None

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
                    f'<div class="monto"{destaque}>{pesos(dia.total)}</div>'
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
            (d.total for d in con_datos if d.fecha == hoy), mejor_dia.total
        )
        diferencia = hoy_total - mejor_dia.total
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


def paso_resultados(promos: list[Promo], fallos: dict[str, str]) -> None:
    """Ultimo paso: donde conviene comprar la lista ya ajustada."""
    resultado = _resultado_actual()
    if resultado is None:
        return

    preferencias = Preferencias(
        entidades=frozenset(st.session_state.get("entidades") or ()),
        modalidad=st.session_state.get("modalidad", "sucursal"),
        incluir_sin_banco=bool(st.session_state.get("incluir_sin_banco")),
    )
    hoy = dt.date.today()
    veredictos = evaluar(
        resultado.cotizaciones, promos, dia=hoy, preferencias=preferencias
    )
    ganador = veredictos[0] if veredictos else None

    st.markdown(
        '<div class="hero"><h1>'
        + (
            f"Te conviene {ganador.nombre}"
            if ganador
            else "No pudimos comparar tu lista"
        )
        + "</h1><p>"
        + (
            f"{len(resultado.items)} productos en "
            f"{len(resultado.cadenas)} cadenas, con los precios de ahora."
        )
        + "</p></div>",
        unsafe_allow_html=True,
    )
    tema.barra_de_pasos(PASOS, "resultados")

    if fallos:
        detalle = ", ".join(
            f"{CADENAS[c].nombre}: {m}" for c, m in fallos.items() if c in CADENAS
        )
        st.warning(
            f"No se pudieron leer las promociones de {len(fallos)} cadena(s). Los "
            "precios siguen siendo correctos, pero a esas cadenas no se les aplica "
            f"descuento. ({detalle})"
        )

    if not preferencias.entidades:
        st.info(
            "Volvé al paso de medios de pago y elegí tus bancos: la comparación "
            "va a incluir los descuentos que te correspondan."
        )

    mostrar_ranking(veredictos, total_items=len(resultado.items))

    pestanas = st.tabs(
        ["Detalle por producto", "Próximos 7 días", "Promociones vigentes"]
    )

    with pestanas[0]:
        tabla_por_producto(resultado)

    with pestanas[1]:
        tema.titulo("Qué día conviene comprar", "con los precios de hoy")
        st.markdown(
            '<div class="nota">Los precios son los de ahora: lo que cambia día a '
            "día son las promociones bancarias, que se conocen de antemano.</div>",
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
        mostrar_promociones(promos, resultado.cadenas, preferencias, hoy)

    st.markdown("")
    st.markdown('<div class="navegacion">', unsafe_allow_html=True)
    columnas = st.columns([1, 1, 2])
    if columnas[0].button("← Marcas y envases", width="stretch"):
        ir_a("ajustes")
    if columnas[1].button("Editar lista", width="stretch"):
        ir_a("productos")
    st.markdown("</div>", unsafe_allow_html=True)


def main() -> None:
    """Un paso por pantalla, en el orden en que se toman las decisiones.

    Primero que comprar, despues donde, despues con que se paga y recien
    entonces los precios. Cada pantalla hace una sola pregunta: antes estaba
    todo junto en una barra lateral y habia que entender la app entera antes de
    poder usarla.
    """
    with st.spinner("Leyendo las promociones de las cinco cadenas..."):
        promos, fallos = cargar_promociones()

    paso = paso_actual()
    _volver_al_tope()
    if paso == "cadenas":
        paso_cadenas()
    elif paso == "pago":
        paso_pago(promos)
    elif paso == "ajustes":
        paso_ajustes()
    elif paso == "resultados":
        paso_resultados(promos, fallos)
    else:
        paso_productos()


if __name__ == "__main__":
    main()
