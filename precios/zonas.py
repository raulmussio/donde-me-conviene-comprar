"""Zonas de compra de CABA y el Gran Buenos Aires.

Responsabilidad unica: traducir "compro en zona sur" a lo que cada cadena
necesita para devolver los precios de esa zona.

Cada cadena resuelve la zona de una forma distinta, y una no la resuelve:

- Carrefour, Dia y ChangoMas aceptan un `regionId` que se obtiene de su API de
  regiones a partir de un codigo postal. Ese id solo surte efecto en el buscador
  moderno (`intelligent-search`); el endpoint de catalogo clasico lo ignora en
  silencio, que es la clase de detalle que hace creer que algo anda cuando no.
- Coto no regionaliza la busqueda: devuelve el precio de todas sus sucursales en
  la misma respuesta. La zona se aplica despues, quedandose con las sucursales
  que corresponden.
- Jumbo no expone ninguna forma publica de pedir precios por zona. Sus canales
  de venta responden `sc is inactive` y su API de regiones devuelve un error.
  Para Jumbo se informa el precio de su tienda online, que es el unico que
  publica.

Cuanto cambia el precio segun la zona no es parejo. Carrefour cotiza igual en
CABA y en todo el GBA, y recien cambia entre provincias. ChangoMas si distingue:
la misma leche Las Tres Ninas de 1 L vale $2.749 en CABA y $2.719 en zona sur, y
en zona sur ademas aparece una marca mas barata que en CABA no esta.
"""

from __future__ import annotations

import html
import logging
import re
import threading
from dataclasses import dataclass

import requests

from precios.base import TIEMPO_ESPERA

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class Zona:
    """Una zona de compra y como la identifica cada cadena."""

    clave: str
    nombre: str
    # Codigo postal representativo, para pedirle el `regionId` a las cadenas
    # VTEX. No hace falta que sea el del usuario: dentro de una misma zona todas
    # devuelven la misma region.
    codigo_postal: str
    # Como escribe Coto esta zona en la direccion de sus sucursales.
    etiqueta_coto: str
    # Punto de referencia para pedir sucursales cercanas, como "longitud;latitud"
    # que es el orden en que lo manda el propio sitio.
    coordenadas: str


ZONAS: dict[str, Zona] = {
    "caba": Zona(
        clave="caba",
        nombre="Ciudad de Buenos Aires",
        codigo_postal="1425",
        etiqueta_coto="CAPITAL FEDERAL",
        # Obelisco
        coordenadas="-58.3816;-34.6037",
    ),
    "gba_norte": Zona(
        clave="gba_norte",
        nombre="GBA Norte",
        codigo_postal="1636",
        etiqueta_coto="ZONA NORTE",
        # San Isidro
        coordenadas="-58.5126;-34.4708",
    ),
    "gba_oeste": Zona(
        clave="gba_oeste",
        nombre="GBA Oeste",
        codigo_postal="1704",
        etiqueta_coto="ZONA OESTE",
        # Moron
        coordenadas="-58.6198;-34.6534",
    ),
    "gba_sur": Zona(
        clave="gba_sur",
        nombre="GBA Sur",
        codigo_postal="1878",
        etiqueta_coto="ZONA SUR",
        # Quilmes
        coordenadas="-58.2543;-34.7203",
    ),
}

ZONA_POR_DEFECTO = "caba"

URL_SUCURSALES_COTO = "https://www.coto.com.ar/sucursales/index.asp"

# Las respuestas de region y el listado de sucursales cambian muy de vez en
# cuando, asi que se guardan en memoria mientras dure el proceso.
_candado = threading.Lock()
_regiones: dict[tuple[str, str], str | None] = {}
_sucursales: list["SucursalCoto"] | None = None


@dataclass(frozen=True)
class SucursalCoto:
    """Una sucursal de Coto, tal como la publica su listado."""

    numero: str
    nombre: str
    direccion: str
    zona: str

    @property
    def etiqueta(self) -> str:
        return f"{self.nombre} - {self.direccion}"


def region_vtex(
    sesion: requests.Session, *, dominio: str, codigo_postal: str
) -> str | None:
    """`regionId` de una tienda VTEX para un codigo postal.

    Devuelve None si la cadena no soporta consultar regiones, que es el caso de
    Jumbo. Un fallo aca no es grave: sin region se cotiza la lista por defecto.
    """
    clave = (dominio, codigo_postal)
    with _candado:
        if clave in _regiones:
            return _regiones[clave]

    encontrada: str | None = None
    try:
        respuesta = sesion.get(
            f"https://{dominio}/api/checkout/pub/regions",
            params={"country": "ARG", "postalCode": codigo_postal},
            timeout=TIEMPO_ESPERA,
        )
        if respuesta.status_code == 200:
            cuerpo = respuesta.json()
            # Las cadenas que no lo soportan responden 200 con un objeto de
            # error en vez de la lista esperada.
            if isinstance(cuerpo, list) and cuerpo:
                encontrada = cuerpo[0].get("id") or None
    except (requests.RequestException, ValueError) as exc:
        LOGGER.info("sin region para %s (%s): %s", dominio, codigo_postal, exc)

    with _candado:
        _regiones[clave] = encontrada
    return encontrada


def sucursales_coto(sesion: requests.Session) -> list[SucursalCoto]:
    """Listado de sucursales de Coto, leido de su pagina publica.

    Se lee en vez de escribirse a mano para que abrir o cerrar una sucursal no
    obligue a tocar el codigo. Si la pagina falla se devuelve una lista vacia y
    Coto cotiza sin filtro de zona, que es el comportamiento anterior.
    """
    global _sucursales
    with _candado:
        if _sucursales is not None:
            return _sucursales

    encontradas: list[SucursalCoto] = []
    try:
        respuesta = sesion.get(URL_SUCURSALES_COTO, timeout=TIEMPO_ESPERA)
        if respuesta.status_code == 200:
            # La pagina no declara bien su codificacion y llega en latin-1.
            respuesta.encoding = respuesta.apparent_encoding or "latin-1"
            encontradas = _parsear_sucursales(respuesta.text)
    except requests.RequestException as exc:
        LOGGER.warning("no se pudo leer el listado de sucursales de Coto: %s", exc)

    with _candado:
        _sucursales = encontradas
    return encontradas


def _parsear_sucursales(pagina: str) -> list[SucursalCoto]:
    """Extrae las filas de la tabla de sucursales.

    Cada fila trae numero, nombre y una direccion que termina en la zona
    ("Aguero 616 - CAPITAL FEDERAL"), que es de donde sale la zona.
    """
    salida: list[SucursalCoto] = []
    for fila in re.findall(r"<tr[^>]*>(.*?)</tr>", pagina, re.S | re.I):
        celdas = [
            re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", celda))).strip()
            for celda in re.findall(r"<td[^>]*>(.*?)</td>", fila, re.S | re.I)
        ]
        if len(celdas) < 3 or not re.fullmatch(r"\d+", celdas[0]):
            continue
        direccion = celdas[2]
        partes = direccion.rsplit(" - ", 1)
        zona = partes[1].strip().upper() if len(partes) > 1 else ""
        salida.append(
            SucursalCoto(
                # En los precios el numero viene con tres digitos ("091") y en
                # el listado sin rellenar ("91").
                numero=celdas[0].zfill(3),
                nombre=celdas[1],
                direccion=partes[0].strip(),
                zona=zona,
            )
        )
    return salida


def sucursales_coto_de(sesion: requests.Session, zona: Zona) -> list[SucursalCoto]:
    """Sucursales de Coto que pertenecen a una zona."""
    return [
        sucursal
        for sucursal in sucursales_coto(sesion)
        if sucursal.zona == zona.etiqueta_coto
    ]


def tiendas_coto_de(sesion: requests.Session, zona: Zona) -> frozenset[str]:
    """Numeros de sucursal de Coto en una zona, para filtrar sus precios."""
    return frozenset(sucursal.numero for sucursal in sucursales_coto_de(sesion, zona))


def zona_de(clave: str | None) -> Zona:
    """La zona pedida, o la de por defecto si la clave no existe."""
    return ZONAS.get(clave or "", ZONAS[ZONA_POR_DEFECTO])


# ---------------------------------------------------------------------------
# Sucursales de cada cadena en la zona
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Sucursal:
    """Una sucursal concreta, ya sea de Coto o de una cadena VTEX."""

    cadena: str
    nombre: str
    direccion: str
    localidad: str = ""

    @property
    def etiqueta(self) -> str:
        partes = [self.nombre]
        # Varias cadenas repiten la calle como nombre del punto; no hace falta
        # decirla dos veces.
        if self.direccion and self.direccion.lower() not in self.nombre.lower():
            partes.append(self.direccion)
        if self.localidad and self.localidad.lower() not in " ".join(partes).lower():
            partes.append(self.localidad)
        return " - ".join(partes)


MAXIMO_SUCURSALES = 12


def sucursales_vtex(
    sesion: requests.Session, *, cadena: str, dominio: str, zona: Zona
) -> list[Sucursal]:
    """Sucursales de una cadena VTEX cerca del punto de referencia de la zona.

    Sale de `pickup-points`, que es el listado de puntos de retiro y coincide
    con los locales fisicos. Jumbo devuelve una lista vacia, igual que con todo
    lo demas referido a zonas.
    """
    url = f"https://{dominio}/api/checkout/pub/pickup-points"
    try:
        respuesta = sesion.get(
            url,
            params={"geoCoordinates": zona.coordenadas, "countryCode": "ARG"},
            timeout=TIEMPO_ESPERA,
        )
        if respuesta.status_code != 200:
            return []
        items = (respuesta.json() or {}).get("items") or []
    except (requests.RequestException, ValueError) as exc:
        LOGGER.info("sin sucursales para %s: %s", cadena, exc)
        return []

    salida: list[Sucursal] = []
    vistas: set[tuple[str, str]] = set()
    for entrada in items:
        punto = entrada.get("pickupPoint") or {}
        direccion = punto.get("address") or {}
        nombre = _limpiar_nombre(punto.get("friendlyName") or "")
        calle = " ".join(
            str(parte).strip()
            for parte in (direccion.get("street"), direccion.get("number"))
            if parte
        ).strip()
        # Algunas entradas traen el texto literal "None" en vez de venir vacias.
        localidad = ""
        for campo in (direccion.get("neighborhood"), direccion.get("city")):
            texto = str(campo or "").strip()
            if texto and texto.lower() != "none":
                localidad = texto
                break
        # ChangoMas usa el campo de calle para anunciar la modalidad de retiro
        # ("Retira sin bajarte del auto!"). Una direccion sin numero y con esa
        # redaccion no es una direccion.
        if calle and not re.search(r"\d", calle) and re.search(r"retir|pickup|auto", calle, re.I):
            calle = ""
        if not nombre and not calle:
            continue
        # Las cadenas repiten el mismo local con varias modalidades de retiro.
        firma = (nombre.lower(), calle.lower())
        if firma in vistas:
            continue
        vistas.add(firma)
        salida.append(
            Sucursal(cadena=cadena, nombre=nombre or calle, direccion=calle, localidad=localidad)
        )
        if len(salida) >= MAXIMO_SUCURSALES:
            break
    return salida


def _limpiar_nombre(nombre: str) -> str:
    """Saca la modalidad de entrega con que las cadenas bautizan sus puntos.

    Los locales vienen como "Retira en Tienda Quilmes" o
    "Pickup HIPERChangoMas Avellaneda - Retira sin bajarte del auto!": lo util
    es el local, no como se retira.
    """
    limpio = re.sub(
        r"^\s*(retir[aoá]?\s+en\s+(tienda|sucursal)?|pickup|retiro\s+en\s+tienda)\s*",
        "",
        nombre,
        flags=re.IGNORECASE,
    )
    # Lo que va despues de un guion suele ser el eslogan de la modalidad.
    cabeza, separador, cola = limpio.partition(" - ")
    if separador and re.search(r"retir|pickup|auto|envio|delivery", cola, re.IGNORECASE):
        limpio = cabeza
    return limpio.strip(" -") or nombre.strip()


def sucursales_coto_como(zona: Zona, sucursales: list[SucursalCoto]) -> list[Sucursal]:
    """Adapta las sucursales de Coto al tipo comun."""
    # Coto nombra sus sucursales por la localidad ("Avellaneda", "Abasto"), asi
    # que repetir la zona al final no agrega nada.
    return [
        Sucursal(
            cadena="coto",
            nombre=sucursal.nombre.title(),
            direccion=sucursal.direccion,
        )
        for sucursal in sucursales[:MAXIMO_SUCURSALES]
    ]
