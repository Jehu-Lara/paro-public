"""Excepciones de dominio de la capa de persistencia.

No son ``HTTPException``: la API (Sprint 3) las traduce a codigos de estado.
Mantenerlas aqui, en vez de en ``paro.api``, evita que ``paro.db`` dependa de
FastAPI y le da a quien llama suficiente informacion para construir un 409
util sin volver a consultar la fila.
"""

from __future__ import annotations

from typing import Any

__all__ = ["DuplicateWithDifferentPayloadError"]


class DuplicateWithDifferentPayloadError(Exception):
    """La clave de idempotencia (``source``, ``external_id``) ya existe con otros datos.

    Se lanza cuando un insert idempotente encuentra una fila existente con la
    misma clave pero cuyos campos de negocio difieren del payload entrante
    (ver ``paro.db.repositories``). Distinto de un simple duplicado: ese caso
    es un no-op silencioso, no una excepcion.
    """

    def __init__(
        self,
        *,
        entity: str,
        source: str,
        external_id: str,
        differing_fields: dict[str, tuple[Any, Any]],
    ) -> None:
        self.entity = entity
        self.source = source
        self.external_id = external_id
        self.differing_fields = differing_fields
        fields = ", ".join(sorted(differing_fields))
        super().__init__(
            f"{entity}: source={source!r} external_id={external_id!r} ya existe con "
            f"datos distintos en: {fields}"
        )
