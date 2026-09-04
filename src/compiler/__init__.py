"""Logical, QEC-protocol, and physical compiler-boundary contracts."""

from .compiler import expand_to_qec_protocol
from .qec_ir import EncodedBlock, QECOp, QECOpKind, QECProtocolIR, TransversalPair

__all__ = [
    "EncodedBlock", "QECOp", "QECOpKind", "QECProtocolIR",
    "TransversalPair", "expand_to_qec_protocol",
]


