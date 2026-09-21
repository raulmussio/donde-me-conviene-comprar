"""Registro de las cadenas comparadas y punto de entrada unico de precios.

Responsabilidad unica: saber que cadena se consulta con que cliente y con que
parametros de zona. El resto de la app pide precios por aca y no necesita saber
si detras hay VTEX o Constructor.io, ni como resuelve cada una la zona.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import requests

from nucleo.modelos import Oferta
from precios import coto as cliente_coto
from precios import vtex as cliente_vtex
from precios import zonas

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class Cadena:
    """Como consultar una cadena puntual."""

    clave: str
    nombre: str
    motor: str  # "vtex" | "coto"
    dominio: str
    # Canal de venta de VTEX. Solo se usa en la busqueda clasica; la zona se
    # resuelve con `regionId`. Ver `precios/zonas.py`.
    canal_venta: str | None = None
    # False cuando la cadena no publica ninguna forma de pedir precios por zona.
    # Es el caso de Jumbo: sus canales responden "sc is inactive" y su API de
    # regiones devuelve un error.
    soporta_zona: bool = True
    url_promociones: str = ""


CADENAS: dict[str, Cadena] = {
    "carrefour": Cadena(
        clave="carrefour",
        nombre="Carrefour",
        motor="vtex",
        dominio="www.carrefour.com.ar",
        url_promociones="https://www.carrefour.com.ar/descuentos-bancarios",
    ),
    "coto": Cadena(
        clave="coto",
        nombre="Coto",
        motor="coto",
        dominio="www.coto.com.ar",
        url_promociones="https://www.coto.com.ar/descuentos",
    ),
    "jumbo": Cadena(
        clave="jumbo",
        nombre="Jumbo",
        motor="vtex",
        dominio="www.jumbo.com.ar",
        soporta_zona=False,
        url_promociones="https://www.jumbo.com.ar/descuentos-del-dia",
    ),
    "dia": Cadena(
        clave="dia",
        nombre="Dia",
        motor="vtex",
        dominio="diaonline.supermercadosdia.com.ar",
        url_promociones="https://diaonline.supermercadosdia.com.ar/medios-de-pago-y-promociones",
    ),
    "changomas": Cadena(
        clave="changomas",
        nombre="ChangoMas",
        motor="vtex",
        dominio="www.masonline.com.ar",
        url_promociones="https://www.masonline.com.ar/promociones-bancarias",
    ),
}


def buscar(
    sesion: requests.Session,
    *,
    clave_cadena: str,
    consulta: str,
    zona: zonas.Zona | None = None,
) -> list[Oferta]:
    """Busca un termino en una cadena y devuelve sus ofertas sin puntuar.

    Cada cadena aplica la zona a su manera: las VTEX con un `regionId` que se
    pide por codigo postal, y Coto quedandose con las sucursales de esa zona
    entre todas las que vienen en la respuesta.
    """
    cadena = CADENAS.get(clave_cadena)
    if cadena is None:
        raise KeyError(f"cadena desconocida: {clave_cadena}")

    if cadena.motor == "coto":
        sucursales = zonas.tiendas_coto_de(sesion, zona) if zona else None
        return cliente_coto.buscar(
            sesion, consulta=consulta, sucursales=sucursales or None
        )

    region = None
    if zona and cadena.soporta_zona:
        region = zonas.region_vtex(
            sesion, dominio=cadena.dominio, codigo_postal=zona.codigo_postal
        )

    return cliente_vtex.buscar(
        sesion,
        cadena=cadena.clave,
        dominio=cadena.dominio,
        consulta=consulta,
        region_id=region,
        canal_venta=cadena.canal_venta,
    )
