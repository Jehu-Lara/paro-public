"""Nombres de las advertencias de calidad de datos que emite el dominio.

El motor de OEE nunca oculta un problema de datos convirtiendolo en un ``0.0``
silencioso ni lo esconde detras de una excepcion generica. En su lugar, el
componente afectado se vuelve ``None`` y se agrega uno de estos nombres a
``OeeResult.warnings``, para que quien consuma el resultado sepa exactamente
que paso y por que.
"""

from enum import StrEnum

__all__ = ["Warning"]


class Warning(StrEnum):
    """Advertencias nombradas que puede emitir :func:`paro.domain.oee.calculate_oee`."""

    ZERO_PLANNED_TIME = "ZERO_PLANNED_TIME"
    """El tiempo de produccion planeado es cero: no se puede calcular Availability."""

    ZERO_RUN_TIME = "ZERO_RUN_TIME"
    """El tiempo operativo es cero: no se puede calcular Performance."""

    ZERO_TOTAL_COUNT = "ZERO_TOTAL_COUNT"
    """El conteo total es cero: no se puede calcular Quality."""

    PERFORMANCE_OVER_100 = "PERFORMANCE_OVER_100"
    """Performance crudo supera 100%; suele indicar un Ideal Cycle Time mal
    configurado. Se conserva el valor crudo junto con uno limitado a 100%
    para presentacion."""

    OPEN_EVENT_CLIPPED = "OPEN_EVENT_CLIPPED"
    """Al menos un evento de paro seguia abierto (sin fin) y se cerro usando
    ``as_of`` para poder incluirlo en el calculo."""
