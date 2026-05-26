"""Generic dice-rule IR engine.

The check IR runtime is the deterministic layer behind TRPG dice markers. It
executes already-normalized ``resolution_ir_v1_1`` procedures, computes tiers,
resource deltas, and flags, then hands those facts back to the GM layer for
narration.

Rulebooks are now compiled through the direct IR compiler in ``compile_direct``.
The older rule-facts template compiler was removed from the public package API
so runtime code cannot accidentally route through that legacy path.
"""

from .compile_direct import (
    COMPILER_STRATEGY,
    DEFAULT_DICE_COMPILER_MODEL,
    DiceRuleCompilerError,
    compile_to_ir_direct,
)
from .core import (
    DiceIRExecutionError,
    DiceIRManualResolutionRequired,
    DiceIRValidationError,
    run_resolution_ir,
)

__all__ = [
    "COMPILER_STRATEGY",
    "DEFAULT_DICE_COMPILER_MODEL",
    "DiceIRExecutionError",
    "DiceIRManualResolutionRequired",
    "DiceIRValidationError",
    "DiceRuleCompilerError",
    "compile_to_ir_direct",
    "run_resolution_ir",
]
