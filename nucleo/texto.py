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

# Palabras que nombran lo mismo. Cada grupo se reduce a su primer termino antes
# de comparar, para que el nombre del producto y el del pedido caigan en el
# mismo lugar aunque esten escritos distinto.
#
# El caso que obliga a esto es el papel de cocina: en las gondolas argentinas se
# llama "rollo de cocina" y casi ningun producto dice "papel". Sin la
# equivalencia, pedir "papel de cocina" descarta los rollos de las cinco cadenas
# y se queda con un portarrollos de $36.249.
EQUIVALENCIAS: tuple[tuple[str, ...], ...] = (
    ("papel", "rollo"),
    ("bebida", "gaseosa", "refresco"),
    ("detergente", "lavavajilla", "lavavajillas"),
    ("descremado", "descremada", "desnatada"),
    ("semidescremado", "semidescremada"),
    ("light", "dietetica", "dietetico", "diet"),
    ("integral", "integrales"),
)

# Cuantas reescrituras de la busqueda se prueban como respaldo, por cadena.
MAXIMO_VARIANTES = 2

# Sinonimos frecuentes. La clave se reemplaza por el valor antes de comparar.
SINONIMOS = {
    variante: grupo[0] for grupo in EQUIVALENCIAS for variante in grupo[1:]
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

# Cuenta de unidades de un pack, escrita como "x3", "3 u", "3 ud" o "4 unid".
# Se limita a dos digitos para no confundirla con la cantidad de panos o de
# metros, que en estos productos viene en el mismo nombre: un rollo de cocina se
# llama "x3 40 panos" y un papel higienico "4 u. x 80 m.".
_RE_CONTEO = re.compile(
    r"\bx\s*(?P<a>\d{1,2})\b"
    r"|\b(?P<b>\d{1,2})\s*(?:u|ud|uds|un|unid|unidad|unidades|rollos?)\b",
    re.IGNORECASE,
)


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
    return set(tokenizar_ordenado(texto))


def tokenizar_ordenado(texto: str) -> list[str]:
    """Los mismos tokens, en el orden en que aparecen.

    El orden importa para saber si lo que pediste es el producto o solo un
    ingrediente suyo: en los supermercados el tipo de producto va al principio
    del nombre. "Leche Ilolay 1 L" es leche; "Chocolate con leche Bariloche" no.
    """
    salida: list[str] = []
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
        salida.append(SINONIMOS.get(token, token))
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
    if ultimo:
        return ultimo

    # Ni peso ni volumen: puede ser un pack contado por unidades. Se toma la
    # primera cuenta que aparezca, que es la del envase; lo que viene despues
    # suele ser el detalle del contenido ("x3 40 panos").
    conteo = _RE_CONTEO.search(plano)
    if conteo:
        crudo = conteo.group("a") or conteo.group("b")
        return _convertir(crudo, "un") or (None, None)
    return None, None


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


def variantes_de_consulta(consulta: str) -> list[str]:
    """Otras formas de escribir la misma busqueda, para reintentar en la cadena.

    Los buscadores de los supermercados no conocen sinonimos: pedir
    "papel de cocina" devuelve 1 resultado en Carrefour, 1 en Jumbo y ninguno en
    ChangoMas, mientras que "rollo de cocina" devuelve 12, 12 y 12. Cambiar la
    palabra es de lejos lo que mas mejora los resultados, mucho mas que afinar
    la puntuacion.

    Devuelve solo las variantes distintas del texto original.
    """
    palabras = normalizar(consulta).split()
    if not palabras:
        return []

    # Solo se sustituye la primera palabra, que es la que nombra el producto y
    # la que mas pesa en el buscador de la cadena. Cambiar un adjetivo
    # ("descremada" por "desnatada") no cambia los resultados y gasta una
    # consulta.
    cabeza = palabras[0]
    salida: list[str] = []
    for grupo in EQUIVALENCIAS:
        if cabeza not in grupo:
            continue
        for alternativa in grupo:
            if alternativa == cabeza:
                continue
            candidata = " ".join([alternativa, *palabras[1:]])
            if candidata not in salida:
                salida.append(candidata)
    return salida[:MAXIMO_VARIANTES]


def pesos(monto: float) -> str:
    """Formatea un monto en pesos al estilo argentino: $1.234,56."""
    entero, _, decimal = f"{monto:,.2f}".partition(".")
    return "$" + entero.replace(",", ".") + "," + decimal
