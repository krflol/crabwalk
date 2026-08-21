from dataclasses import dataclass
from typing import List, Optional, Any, Dict, Union

@dataclass
class TypeIR:
    name: str
    generics: List['TypeIR'] = None
    
    def __post_init__(self):
        if self.generics is None:
            self.generics = []

@dataclass
class ExprIR:
    pass

@dataclass
class StmtIR:
    pass

@dataclass
class FunctionIR:
    name: str
    args: List[tuple[str, TypeIR]]
    returns: TypeIR
    body: List[StmtIR]
    detach: bool

@dataclass
class StructIR:
    name: str
    fields: List[tuple[str, TypeIR]]
    derives: List[str]

@dataclass
class EnumIR:
    name: str
    variants: List[str]
    derives: List[str]

@dataclass
class ModuleIR:
    name: str
    functions: List[FunctionIR]
    structs: List[StructIR]
    enums: List[EnumIR]
    crates: Dict[str, dict]
