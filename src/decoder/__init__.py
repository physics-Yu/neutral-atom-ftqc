"""Syndrome and decoder boundary contracts."""

from .decoder import (
    Decoder, DecoderInput, DecoderResult, DecoderStatus, IdealErasureAwareDecoder,
    IdealSingleErrorDecoder,
    PauliFrameDelta, PhysicalCorrection,
)
from .syndrome import PauliError, SyndromeHistory, SyndromeSample, simulate_single_pauli_syndrome

__all__ = [
    "Decoder", "DecoderInput", "DecoderResult", "DecoderStatus",
    "IdealErasureAwareDecoder", "IdealSingleErrorDecoder", "PauliError", "PauliFrameDelta",
    "PhysicalCorrection", "SyndromeHistory", "SyndromeSample",
    "simulate_single_pauli_syndrome",
]

