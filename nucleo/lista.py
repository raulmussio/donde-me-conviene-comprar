"""Lectura de la lista de compras escrita a mano.

Responsabilidad unica: convertir el texto libre que escribe el usuario en
objetos `ItemLista`, una por linea.

Reconoce cantidades explicitas al principio ("3x leche", "3 x leche") o al
final ("leche x3"). Deliberadamente NO interpreta un numero suelto como
cantidad: en "1 kg de yerba" el 1 es el envase, no la cantidad, y confundirlos
duplicaria el total sin que se note.
"""

from __future__ import annotations

import re

from nucleo.modelos import ItemLista
from nucleo.texto import parsear_envase

# "3x ", "3 x ", "3X " al comienzo de la linea.
_RE_CANTIDAD_INICIO = re.compile(r"^\s*(\d{1,2})\s*[xX]\s+?", re.UNICODE)
# "... x3" o "... x 3" al final.
_RE_CANTIDAD_FINAL = re.compile(r"\s+[xX]\s*(\d{1,2})\s*$")

# Lineas que son comentarios o separadores y no productos.
_RE_IGNORAR = re.compile(r"^\s*(#|//|-{2,}|\*{2,})")

MAXIMO_ITEMS = 40


def parsear_lista(texto: str) -> list[ItemLista]:
    """Convierte el texto de la lista en items, salteando vacios y comentarios."""
    items: list[ItemLista] = []
    for linea in (texto or "").splitlines():
        item = parsear_linea(linea)
        if item:
            items.append(item)
        if len(items) >= MAXIMO_ITEMS:
            break
    return items


def parsear_linea(linea: str) -> ItemLista | None:
    """Convierte una linea suelta en ItemLista. None si no hay producto."""
    crudo = (linea or "").strip().lstrip("-*\u2022 ").strip()
    if not crudo or _RE_IGNORAR.match(linea or ""):
        return None

    cantidad = 1

    coincidencia = _RE_CANTIDAD_INICIO.match(crudo)
    if coincidencia:
        cantidad = int(coincidencia.group(1))
        crudo = crudo[coincidencia.end() :].strip()
    else:
        coincidencia = _RE_CANTIDAD_FINAL.search(crudo)
        if coincidencia:
            cantidad = int(coincidencia.group(1))
            crudo = crudo[: coincidencia.start()].strip()

    if not crudo:
        return None

    magnitud, unidad = parsear_envase(crudo)
    return ItemLista(
        texto=crudo,
        cantidad=max(1, min(cantidad, 99)),
        magnitud_objetivo=magnitud,
        unidad_objetivo=unidad,
    )
