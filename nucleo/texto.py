"""Normalizacion de texto y lectura del envase a partir del nombre del producto.

Responsabilidad unica: convertir cadenas sucias en algo comparable. Las cinco
cadenas escriben el mismo producto de formas distintas ("Leche La Serenisima
Entera 1L", "LECHE ENTERA LA SERENISIMA x 1 lt", "Leche entera 1000 cc") y sin
esta capa cualquier comparacion es ruido.

No hace red y no conoce el modelo de dominio.
"""

from __future__ import annotations

import re
import unicodedata

# Palabras que aparecen en casi todos los nombres y no distinguen nada.
VACIAS = frozenset(
    """
    de del la el los las un una unos unas y con sin para por en al
    x cada pack unidad unidades und uni u caja bolsa botella sachet paquete
    envase estuche lata frasco pote doy doypack pouch tetra brik ttb
    """.split()
)

# Sinonimos frecuentes. La clave se reemplaza por el valor antes de comparar,
# para que "gaseosa cola" y "bebida cola" caigan en el mismo lugar.
SINONIMOS = {
    "gaseosa": "bebida",
    "refresco": "bebida",
    "descremada": "descremado",
    "desnatada": "descremado",
    "semidescremada": "semidescremado",
    "dietetica": "light",
    "diet": "light",
    "integrales": "integral",
    "lavandina": "lavandina",
    "papel": "papel",
}

# Unidades reconocidas y su factor hacia la unidad base (kg para peso, L para
# volumen). "un" queda como conteo, sin conversion.
_UNIDADES = {
    "kg": ("kg", 1.0),
    "kgs": ("kg", 1.0),
    "kgm": ("kg", 1.0),
    "kilo": ("kg", 1.0),
    "kilos": ("kg", 1.0),
    "g": ("kg", 0.001),
    "gr": ("kg", 0.001),
    "grs": ("kg", 0.001),
    "grm": ("kg", 0.001),
    "gramo": ("kg", 0.001),
    "gramos": ("kg", 0.001),
    "mg": ("kg", 0.000001),
    "l": ("l", 1.0),
    "lt": ("l", 1.0),
    "lts": ("l", 1.0),
    "litro": ("l", 1.0),
    "litros": ("l", 1.0),
    "ml": ("l", 0.001),
    "cc": ("l", 0.001),
    "cm3": ("l", 0.001),
    "un": ("un", 1.0),
    "u": ("un", 1.0),
    "unidad": ("un", 1.0),
    "unidades": ("un", 1.0),
    "rollo": ("un", 1.0),
    "rollos": ("un", 1.0),
}

_NUMERO = r"\d+(?:[.,]\d+)?"

# "6x500ml", "3 x 1 L": pack multiplicado. Se captura para poder totalizar.
_RE_PACK = re.compile(
    rf"(?P<n>\d+)\s*[xX*]\s*(?P<mag>{_NUMERO})\s*(?P<uni>[a-z]+)\b", re.IGNORECASE
)
# "900 g", "1,5L", "1 lt"
_RE_SIMPLE = re.compile(rf"(?P<mag>{_NUMERO})\s*(?P<uni>[a-z]+3?)\b", re.IGNORECASE)


def normalizar(texto: str) -> str:
    """Minusculas, sin acentos, sin puntuacion y con espacios colapsados."""
    if not texto:
        return ""
    plano = unicodedata.normalize("NFKD", texto)
    plano = "".join(c for c in plano if not unicodedata.combining(c))
    plano = plano.lower()
    plano = re.sub(r"[^a-z0-9%.,x ]+", " ", plano)
    return re.sub(r"\s+", " ", plano).strip()


def tokenizar(texto: str) -> set[str]:
    """Tokens significativos de un nombre: sin vacias, sin numeros sueltos."""
    salida: set[str] = set()
    for bruto in normalizar(texto).split():
        token = bruto.strip(".,")
        if not token or token in VACIAS:
            continue
        # Un token que es solo numero o solo medida no aporta al parecido
        # semantico; el envase se compara aparte en `parsear_envase`.
        if re.fullmatch(rf"{_NUMERO}[a-z]*", token) and not token.isalpha():
            continue
        if len(token) <= 1:
            continue
        salida.add(SINONIMOS.get(token, token))
    return salida


def parsear_envase(texto: str) -> tuple[float | None, str | None]:
    """Devuelve (magnitud, unidad_base) leyendo el envase del nombre.

    La magnitud sale siempre en la unidad base: kg para peso, l para volumen,
    un para conteo. Un pack se multiplica ("6x500ml" -> 3.0 l).

    Devuelve (None, None) si no hay nada reconocible, que es lo normal en
    frutas y verduras a granel.
    """
    plano = normalizar(texto)
    if not plano:
        return None, None

    pack = _RE_PACK.search(plano)
    if pack:
        convertido = _convertir(pack.group("mag"), pack.group("uni"))
        if convertido:
            magnitud, unidad = convertido
            return magnitud * int(pack.group("n")), unidad

    # Sin pack: se toma la ultima medida del nombre, que suele ser el envase
    # ("Leche 3% Entera 1 L" -> 1 l, no 3%).
    ultimo = None
    for coincidencia in _RE_SIMPLE.finditer(plano):
        convertido = _convertir(coincidencia.group("mag"), coincidencia.group("uni"))
        if convertido:
            ultimo = convertido
    return ultimo if ultimo else (None, None)


# Rango plausible de un envase de supermercado, por unidad base. Fuera de estos
# limites la medida esta mal cargada en el catalogo, no es un producto raro.
# Coto publica hoy "Coca-Cola Sabor Liviano 1,75 Ml" para una botella de 1,75 L:
# leerlo al pie de la letra mete un envase de dos mililitros en la comparacion.
_RANGO_PLAUSIBLE = {
    "kg": (0.002, 50.0),
    "l": (0.005, 50.0),
    "un": (1.0, 500.0),
}


def _convertir(magnitud: str, unidad: str) -> tuple[float, str] | None:
    """Pasa una medida cruda a la unidad base.

    Devuelve None si la unidad no se reconoce o si el tamano resultante no puede
    ser el de un envase real.
    """
    entrada = _UNIDADES.get(unidad.lower())
    if not entrada:
        return None
    base, factor = entrada
    try:
        valor = float(magnitud.replace(",", "."))
    except ValueError:
        return None
    if valor <= 0:
        return None

    convertido = valor * factor
    minimo, maximo = _RANGO_PLAUSIBLE.get(base, (0.0, float("inf")))
    if not minimo <= convertido <= maximo:
        return None
    return convertido, base


def formatear_envase(magnitud: float | None, unidad: str | None) -> str:
    """Texto corto y legible del envase, para mostrar en la tabla."""
    if not magnitud or not unidad:
        return "-"
    if unidad == "kg":
        return f"{magnitud * 1000:.0f} g" if magnitud < 1 else f"{magnitud:g} kg"
    if unidad == "l":
        return f"{magnitud * 1000:.0f} ml" if magnitud < 1 else f"{magnitud:g} L"
    return f"{magnitud:g} un"


def pesos(monto: float) -> str:
    """Formatea un monto en pesos al estilo argentino: $1.234,56."""
    entero, _, decimal = f"{monto:,.2f}".partition(".")
    return "$" + entero.replace(",", ".") + "," + decimal
