"""Identificacion y fijado de marcas a lo largo de las cinco cadenas.

Responsabilidad unica: reconocer que marca es cada oferta y ofrecer la lista de
marcas comparables para un item, de modo que el usuario pueda decir "quiero
Casancrem" y las cinco cadenas coticen Casancrem.

Las cinco cadenas publican la marca en un campo propio y lo llenan bien, pero
cada una la escribe a su manera: la misma marca aparece como `TREGAR`, `Tregar`
y `La Paulina` contra `LA PAULINA`. Se agrupan por su forma normalizada y se
muestra la grafia mas legible de las que se vieron.

A diferencia del envase, fijar la marca es una condicion excluyente: quien pide
Casancrem no quiere que le coticen la segunda marca mas barata. Si una cadena no
la tiene, la respuesta correcta es que no la tiene.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from nucleo.modelos import Oferta
from nucleo.texto import normalizar

LOGGER = logging.getLogger(__name__)

# Valores que las cadenas usan como relleno cuando no hay marca real. No sirven
# para fijar nada porque agrupan productos de origenes distintos.
VACIAS = frozenset(
    {
        "generico",
        "generica",
        "genericos",
        "sin marca",
        "varios",
        "otros",
        "otras",
        "na",
        "n a",
        "ninguna",
        "marca blanca",
    }
)

# Clave que representa "no fijar ninguna marca".
LIBRE = ""

ETIQUETA_LIBRE = "cualquier marca"


@dataclass(frozen=True)
class Marca:
    """Una marca comparable, con las cadenas que la tienen."""

    clave: str
    etiqueta: str
    cadenas: frozenset[str]

    @property
    def es_libre(self) -> bool:
        return self.clave == LIBRE


MARCA_LIBRE = Marca(clave=LIBRE, etiqueta=ETIQUETA_LIBRE, cadenas=frozenset())


def clave_de(oferta: Oferta) -> str:
    """Forma normalizada de la marca de una oferta. Vacia si no tiene una util."""
    plano = normalizar(oferta.marca or "")
    if not plano or plano in VACIAS:
        return LIBRE
    return plano


def coincide(oferta: Oferta, clave: str) -> bool:
    """True si la oferta es de esa marca.

    Se mira primero el campo de marca y despues el nombre del producto: hay
    fichas donde la marca quedo vacia o mal cargada pero el nombre la dice.
    """
    if not clave:
        return True
    if clave_de(oferta) == clave:
        return True
    # Limite de palabra para que una marca corta como "Dia" no dispare dentro de
    # "diario" ni de "media".
    return bool(
        re.search(rf"(?<![a-z0-9]){re.escape(clave)}(?![a-z0-9])", normalizar(oferta.nombre))
    )


def opciones(candidatos_por_cadena: dict[str, list[Oferta]]) -> list[Marca]:
    """Marcas disponibles para un item, de la que mas cadenas tienen a la que menos.

    El orden importa: una marca que esta en las cinco cadenas permite una
    comparacion completa, y una que esta en una sola solo sirve para saber
    cuanto sale ahi.
    """
    cadenas_por_clave: dict[str, set[str]] = {}
    grafias: dict[str, list[str]] = {}

    for cadena, ofertas in candidatos_por_cadena.items():
        for oferta in ofertas:
            clave = clave_de(oferta)
            if not clave:
                continue
            cadenas_por_clave.setdefault(clave, set()).add(cadena)
            grafias.setdefault(clave, []).append((oferta.marca or "").strip())

    encontradas = [
        Marca(
            clave=clave,
            etiqueta=_mejor_grafia(grafias[clave]),
            cadenas=frozenset(cadenas),
        )
        for clave, cadenas in cadenas_por_clave.items()
    ]
    encontradas.sort(key=lambda marca: (-len(marca.cadenas), marca.etiqueta.lower()))
    return encontradas


def _mejor_grafia(vistas: list[str]) -> str:
    """La escritura mas legible entre las que publicaron las cadenas.

    Se prefiere una con mayusculas y minusculas mezcladas ("Casancrem") antes
    que la version gritada ("CASANCREM"), que es como la escriben Coto y Jumbo.
    """
    for texto in vistas:
        if texto and not texto.isupper():
            return texto
    return vistas[0].title() if vistas and vistas[0] else ETIQUETA_LIBRE


def filtrar(ofertas: list[Oferta], clave: str) -> list[Oferta]:
    """Deja solo las ofertas de esa marca. Sin marca fijada, no filtra nada."""
    if not clave:
        return list(ofertas)
    return [oferta for oferta in ofertas if coincide(oferta, clave)]
